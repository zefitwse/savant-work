from __future__ import annotations

import os
import signal
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, "/opt/savant")
sys.path.insert(0, "/opt/savant/adapters/gst")

from savant.api.parser import convert_ts
from savant.gstreamer import GLib, Gst, GstApp
from savant.gstreamer.codecs import Codec
from savant_rs.primitives import EndOfStream, VideoFrame
from savant_rs.py.utils.zeromq import ZeroMQMessage, ZeroMQSource

from gst_plugins.python.savant_rs_video_demux_common import FrameParams, build_caps


class RtmpPreviewSink:
    def __init__(self, rtmp_location: str) -> None:
        self.rtmp_location = rtmp_location
        self.appsrc: Optional[GstApp.AppSrc] = None
        self.pipeline: Optional[Gst.Pipeline] = None
        self.mainloop = GLib.MainLoop()

    def start(self, frame: VideoFrame) -> None:
        if self.pipeline is not None:
            return

        frame_params = FrameParams.from_video_frame(frame)
        if frame_params.codec != Codec.H264:
            raise RuntimeError(f"ZLMediaKit RTMP preview expects H264, got {frame_params.codec}.")

        pipeline = " ! ".join(
            [
                "appsrc name=appsrc emit-signals=false is-live=true format=time",
                "queue",
                "h264parse config-interval=1",
                "flvmux streamable=true",
                f"rtmpsink location={self.rtmp_location} sync=false async=false",
            ]
        )
        self.pipeline = Gst.parse_launch(pipeline)
        self.appsrc = self.pipeline.get_by_name("appsrc")
        self.appsrc.set_caps(build_caps(frame_params, with_framerate=True))

        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", self._on_error)
        bus.connect("message::eos", self._on_eos)

        self.pipeline.set_state(Gst.State.PLAYING)
        print(f"RTMP preview started: {self.rtmp_location}", flush=True)

    def write(self, frame: VideoFrame, data: Optional[bytes]) -> None:
        if not data:
            return
        self.start(frame)
        assert self.appsrc is not None
        buf = Gst.Buffer.new_wrapped(data)
        buf.pts = convert_ts(frame.pts, frame.time_base)
        buf.dts = (
            convert_ts(frame.dts, frame.time_base)
            if frame.dts is not None
            else Gst.CLOCK_TIME_NONE
        )
        buf.duration = (
            convert_ts(frame.duration, frame.time_base)
            if frame.duration is not None
            else Gst.CLOCK_TIME_NONE
        )
        result = self.appsrc.push_buffer(buf)
        if result == Gst.FlowReturn.EOS:
            self.stop()
            return
        if result != Gst.FlowReturn.OK:
            raise RuntimeError(f"Failed to push frame to RTMP pipeline: {result}.")

    def eos(self, _eos: EndOfStream) -> None:
        if self.appsrc is not None:
            self.appsrc.end_of_stream()

    def stop(self) -> None:
        if self.pipeline is not None:
            self.pipeline.set_state(Gst.State.NULL)
            self.pipeline = None
            self.appsrc = None

    def _on_error(self, _bus: Gst.Bus, message: Gst.Message) -> None:
        err, debug = message.parse_error()
        raise RuntimeError(f"RTMP pipeline error: {err}; {debug}")

    def _on_eos(self, _bus: Gst.Bus, _message: Gst.Message) -> None:
        self.stop()


def main() -> None:
    signal.signal(signal.SIGTERM, signal.getsignal(signal.SIGINT))
    zmq_endpoint = os.environ["ZMQ_ENDPOINT"]
    rtmp_location = os.environ.get("RTMP_LOCATION", "rtmp://zlm/live/ppt_cascade_masked")
    source_id = os.environ.get("SOURCE_ID") or None
    source_id_prefix = os.environ.get("SOURCE_ID_PREFIX") or None

    Gst.init(None)
    source = ZeroMQSource(
        zmq_endpoint,
        source_id=source_id,
        source_id_prefix=source_id_prefix,
    )
    sink = RtmpPreviewSink(rtmp_location)

    try:
        source.start()
        for zmq_message in source:
            message: ZeroMQMessage = zmq_message
            if message.message.is_video_frame():
                sink.write(message.message.as_video_frame(), message.content)
            elif message.message.is_end_of_stream():
                sink.eos(message.message.as_end_of_stream())
    except KeyboardInterrupt:
        pass
    finally:
        source.terminate()
        sink.stop()


if __name__ == "__main__":
    main()
