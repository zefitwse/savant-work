import { create } from "zustand";
import { persist } from "zustand/middleware";

export const useAppStore = create()(
  persist(
    (set) => ({
      splitMode: 4,
      videoStreams: [],
      dashboardData: null,
      theme: "dark",
      selectedStreams: [],

      setSplitMode: (mode) => set({ splitMode: mode }),

      setVideoStreams: (streams) => set({ videoStreams: streams }),

      updateStreamStatus: (streamId, status) =>
        set((state) => ({
          videoStreams: state.videoStreams.map((stream) =>
            stream.id === streamId ? { ...stream, status } : stream,
          ),
        })),

      setDashboardData: (data) => set({ dashboardData: data }),

      toggleTheme: () =>
        set((state) => ({ theme: state.theme === "light" ? "dark" : "light" })),

      selectStream: (streamId) =>
        set((state) => ({
          selectedStreams: [...state.selectedStreams, streamId],
        })),

      deselectStream: (streamId) =>
        set((state) => ({
          selectedStreams: state.selectedStreams.filter(
            (id) => id !== streamId,
          ),
        })),
    }),
    {
      name: "surveillance-app-storage",
      partialize: (state) => ({
        theme: state.theme,
        splitMode: state.splitMode,
      }),
    },
  ),
);
