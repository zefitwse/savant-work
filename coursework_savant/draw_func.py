from __future__ import annotations

from typing import Any, Optional

from coursework_savant.privacy_mask import PrivacyMasker, PrivacyPolicy

try:
    from savant.deepstream.drawfunc import NvDsDrawFunc
    from savant.meta.constants import UNTRACKED_OBJECT_ID
    from savant_rs.primitives.geometry import BBox as SavantBBox
except ImportError:
    class NvDsDrawFunc:  # type: ignore[no-redef]
        def __init__(self, **kwargs: Any) -> None:
            pass

    class SavantBBox:  # type: ignore[no-redef]
        def __init__(self, xc: float, yc: float, width: float, height: float) -> None:
            self.xc = xc
            self.yc = yc
            self.width = width
            self.height = height

    UNTRACKED_OBJECT_ID = -1


class RawDrawFunc(NvDsDrawFunc):
    """Draws OSD bounding boxes without privacy masking for admin preview.

    This draw function is used for the raw video output branch, drawing
    detection boxes without any privacy masking applied. The boxes are
    drawn using the same logic as PrivacyAwareDrawFunc to ensure consistency.

    Only primary detector objects (person, vehicle, foreign_object) are drawn,
    secondary detector objects (hardhat, vest, etc.) are not drawn with boxes,
    similar to the masked output behavior.
    """

    def draw_on_frame(self, frame_meta: Any, artist: Any) -> None:
        for obj_meta in frame_meta.objects:
            if obj_meta.is_primary:
                continue

            spec = self._select_draw_spec(obj_meta)
            if spec is None:
                continue

            if spec.bounding_box:
                self._draw_bounding_box(obj_meta, artist, spec.bounding_box)
            if spec.label:
                self._draw_label(obj_meta, artist, spec.label)
            if spec.central_dot:
                self._draw_central_dot(obj_meta, artist, spec.central_dot)

    def _select_draw_spec(self, obj_meta: Any) -> Optional[Any]:
        # Only draw boxes for primary detector objects, not secondary detector objects
        # This ensures consistency with PrivacyAwareDrawFunc which also doesn't draw
        # secondary detection boxes (hardhat, vest, etc.)
        if obj_meta.element_name != "primary_traffic_detector":
            return None

        if len(self.draw_spec) > 0:
            candidates = [
                (obj_meta.element_name, obj_meta.draw_label),
                (obj_meta.element_name, obj_meta.label),
            ]
            if obj_meta.element_name == "primary_traffic_detector":
                if obj_meta.label in {"car", "bicycle", "motorcycle", "bus", "truck"}:
                    candidates.append((obj_meta.element_name, "vehicle"))
                elif obj_meta.label == "road_sign":
                    candidates.append((obj_meta.element_name, "foreign_object"))

            for key in candidates:
                if key in self.draw_spec:
                    return self.override_draw_spec(obj_meta, self.draw_spec[key].copy())
            return None

        if obj_meta.track_id != UNTRACKED_OBJECT_ID:
            return self.default_spec_track_id
        return self.default_spec_no_track_id


class PrivacyAwareDrawFunc(NvDsDrawFunc):
    """Draws OSD and reserves blur rendering for sensitive objects.

    Savant's default draw function matches draw specs by ``draw_label``. The
    event processor enriches ``draw_label`` with secondary attributes, e.g.
    ``person helmet:hardhat``. This override keeps those richer labels visible
    while selecting the draw style by the stable detector label.
    """

    def __init__(
        self,
        enable_preview_mask: bool = True,
        mask_roles: Optional[list[str]] = None,
        preview_role: str = "operator",
        mosaic_block_size: int = 18,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.preview_role = preview_role
        self.privacy_masker = PrivacyMasker(
            PrivacyPolicy(
                enabled=enable_preview_mask,
                masked_roles=mask_roles or ["operator", "guest"],
                mosaic_block_size=mosaic_block_size,
            )
        )

    def draw_on_frame(self, frame_meta: Any, artist: Any) -> None:
        if self.privacy_masker.should_mask(self.preview_role):
            self._mask_sensitive_preview_regions(frame_meta, artist)

        for obj_meta in frame_meta.objects:
            if obj_meta.is_primary:
                continue

            spec = self._select_draw_spec(obj_meta)
            if spec is None:
                continue

            if spec.blur:
                self._blur(obj_meta, artist)
            if spec.bounding_box:
                self._draw_bounding_box(obj_meta, artist, spec.bounding_box)
            if spec.label:
                self._draw_label(obj_meta, artist, spec.label)
            if spec.central_dot:
                self._draw_central_dot(obj_meta, artist, spec.central_dot)

    def _select_draw_spec(self, obj_meta: Any) -> Optional[Any]:
        if len(self.draw_spec) > 0:
            candidates = [
                (obj_meta.element_name, obj_meta.draw_label),
                (obj_meta.element_name, obj_meta.label),
            ]
            if obj_meta.element_name == "primary_traffic_detector":
                if obj_meta.label in {"car", "bicycle", "motorcycle", "bus", "truck"}:
                    candidates.append((obj_meta.element_name, "vehicle"))
                elif obj_meta.label == "road_sign":
                    candidates.append((obj_meta.element_name, "foreign_object"))

            for key in candidates:
                if key in self.draw_spec:
                    return self.override_draw_spec(obj_meta, self.draw_spec[key].copy())
            return None

        if obj_meta.track_id != UNTRACKED_OBJECT_ID:
            return self.default_spec_track_id
        return self.default_spec_no_track_id

    def _mask_sensitive_preview_regions(self, frame_meta: Any, artist: Any) -> None:
        mask_boxes = self.privacy_masker.collect_preview_mask_boxes(
            obj_meta
            for obj_meta in frame_meta.objects
            if not getattr(obj_meta, "is_primary", False)
        )
        for left, top, width, height in mask_boxes:
            try:
                artist.blur(SavantBBox(left + width / 2, top + height / 2, width, height))
            except Exception as exc:
                self.logger.warning(
                    'Got "%s: %s" when trying to privacy-mask bbox %s.',
                    type(exc).__name__,
                    exc,
                    (left, top, width, height),
                    exc_info=exc,
                )
