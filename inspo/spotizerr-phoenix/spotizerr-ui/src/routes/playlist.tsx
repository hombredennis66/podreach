import { Link, useParams } from "@tanstack/react-router";
import { useEffect, useState, useContext, useRef, useCallback } from "react";
import apiClient from "../lib/api-client";
import { useSettings } from "../contexts/settings-context";
import { toast } from "sonner";
import type { LibrespotTrackType, LibrespotPlaylistType, LibrespotPlaylistItemType, LibrespotPlaylistTrackStubType } from "@/types/librespot";
import { QueueContext, getStatus } from "../contexts/queue-context";
import { FaArrowLeft } from "react-icons/fa";

export const Playlist = () => {
  const { playlistId } = useParams({ from: "/playlist/$playlistId" });
  const [playlistMetadata, setPlaylistMetadata] = useState<LibrespotPlaylistType | null>(null);
  const [items, setItems] = useState<LibrespotPlaylistItemType[]>([]);
  const [isWatched, setIsWatched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingTracks, setLoadingTracks] = useState(false);
  const loadingTracksRef = useRef(false);
  const [hasMoreTracks, setHasMoreTracks] = useState(true);
  const tracksOffsetRef = useRef(0);
  const [totalTracks, setTotalTracks] = useState(0);
  const initialLoadCompleteRef = useRef(false);
  const loadMoreFnRef = useRef<(() => Promise<void>) | null>(null);
  
  const context = useContext(QueueContext);
  const { settings } = useSettings();
  const observerRef = useRef<IntersectionObserver | null>(null);
  const loadingRef = useRef<HTMLDivElement>(null);

  if (!context) {
    throw new Error("useQueue must be used within a QueueProvider");
  }
  const { addItem, items: queueItems } = context;

  // Playlist queue status
  const playlistQueueItem = playlistMetadata
    ? queueItems.find(item => item.downloadType === "playlist" && item.spotifyId === (playlistId ?? ""))
    : undefined;
  const playlistStatus = playlistQueueItem ? getStatus(playlistQueueItem) : null;

  useEffect(() => {
    if (playlistStatus === "queued") {
      toast.success(`${playlistMetadata?.name} queued.`);
    } else if (playlistStatus === "error") {
      toast.error(`Failed to queue ${playlistMetadata?.name}`);
    }
  }, [playlistStatus]);

  // Load playlist metadata first (no expanded items)
  useEffect(() => {
    const fetchPlaylist = async () => {
      if (!playlistId) return;
      try {
        const response = await apiClient.get<LibrespotPlaylistType>(`/playlist/info?id=${playlistId}`);
        const data = response.data;
        setPlaylistMetadata(data);
        setTotalTracks(data.tracks.total);
      } catch (err) {
        setError("Failed to load playlist metadata");
        console.error(err);
      }
    };

    const checkWatchStatus = async () => {
      if (!playlistId) return;
      try {
        const response = await apiClient.get(`/playlist/watch/${playlistId}/status`);
        if (response.data.is_watched) {
          setIsWatched(true);
        }
      } catch {
        console.log("Could not get watch status");
      }
    };

    setItems([]);
    tracksOffsetRef.current = 0;
    loadingTracksRef.current = false;
    initialLoadCompleteRef.current = false;
    setHasMoreTracks(true);
    setTotalTracks(0);
    setError(null);
    fetchPlaylist().then(() => {
      initialLoadCompleteRef.current = true;
    });
    checkWatchStatus();
  }, [playlistId]);

  const BATCH_SIZE = 6;

  // Load items progressively by expanding track stubs when needed
  const loadMoreTracks = useCallback(async () => {
    if (!playlistId || loadingTracksRef.current || !hasMoreTracks || !playlistMetadata) return;
    
    const currentOffset = tracksOffsetRef.current;
    
    loadingTracksRef.current = true;
    setLoadingTracks(true);
    try {
      // Fetch full playlist snapshot (stub items)
      const response = await apiClient.get<LibrespotPlaylistType>(`/playlist/info?id=${playlistId}`);
      const allItems = response.data.tracks.items;
      const slice = allItems.slice(currentOffset, currentOffset + BATCH_SIZE);

      // Expand any stubbed track entries by fetching full track info
      const expandedSlice: LibrespotPlaylistItemType[] = await Promise.all(
        slice.map(async (it) => {
          const t = it.track as LibrespotPlaylistTrackStubType | LibrespotTrackType;
          // If track has only stub fields (no duration_ms), fetch full
          if (t && (t as any).id && !("duration_ms" in (t as any))) {
            try {
              const full = await apiClient.get<LibrespotTrackType>(`/track/info?id=${(t as LibrespotPlaylistTrackStubType).id}`).then(r => r.data);
              return { ...it, track: full } as LibrespotPlaylistItemType;
            } catch {
              return it; // fallback to stub if fetch fails
            }
          }
          return it;
        })
      );

      setItems((prev) => [...prev, ...expandedSlice]);
      const loaded = currentOffset + expandedSlice.length;
      tracksOffsetRef.current = loaded;
      if (loaded >= totalTracks) {
        setHasMoreTracks(false);
      }
    } catch (err) {
      console.error("Failed to load tracks:", err);
      toast.error("Failed to load more tracks");
    } finally {
      loadingTracksRef.current = false;
      setLoadingTracks(false);
    }
  }, [playlistId, hasMoreTracks, totalTracks, playlistMetadata]);

  // Keep loadMoreFnRef updated with latest loadMoreTracks
  loadMoreFnRef.current = loadMoreTracks;

  // Intersection Observer for infinite scroll
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMoreTracks && !loadingTracksRef.current && loadMoreFnRef.current) {
          loadMoreFnRef.current();
        }
      },
      { threshold: 0.1 }
    );

    if (loadingRef.current) {
      observer.observe(loadingRef.current);
    }

    observerRef.current = observer;

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [hasMoreTracks]);

  // Kick off initial batch
  useEffect(() => {
    if (playlistMetadata && items.length === 0 && totalTracks > 0 && loadMoreFnRef.current) {
      loadMoreFnRef.current();
    }
  }, [playlistMetadata, items.length, totalTracks]);

  // Auto progressive loading regardless of scroll
  // Only runs after initial load is complete to prevent race condition
  useEffect(() => {
    if (!playlistMetadata || !hasMoreTracks) return;
    if (!initialLoadCompleteRef.current) return;
    if (loadingTracksRef.current) return;
    
    const t = setTimeout(() => {
      if (!loadingTracksRef.current && loadMoreFnRef.current) {
        loadMoreFnRef.current();
      }
    }, 300);
    return () => clearTimeout(t);
  }, [playlistMetadata, hasMoreTracks, items.length]);

  const handleDownloadTrack = (track: LibrespotTrackType) => {
    if (!track?.id) return;
    addItem({ spotifyId: track.id, type: "track", name: track.name });
    toast.info(`Adding ${track.name} to queue...`);
  };

  const handleDownloadPlaylist = () => {
    if (!playlistMetadata) return;
    addItem({
      spotifyId: playlistId!,
      type: "playlist",
      name: playlistMetadata.name,
    });
    toast.info(`Adding ${playlistMetadata.name} to queue...`);
  };

  const handleToggleWatch = async () => {
    if (!playlistId) return;
    try {
      if (isWatched) {
        await apiClient.delete(`/playlist/watch/${playlistId}`);
        toast.success(`Removed ${playlistMetadata?.name} from watchlist.`);
      } else {
        await apiClient.put(`/playlist/watch/${playlistId}`);
        toast.success(`Added ${playlistMetadata?.name} to watchlist.`);
      }
      setIsWatched(!isWatched);
    } catch (err) {
      toast.error("Failed to update watchlist.");
      console.error(err);
    }
  };

  if (error) {
    return <div className="text-red-500 p-8 text-center">{error}</div>;
  }

  if (!playlistMetadata) {
    return <div className="p-8 text-center">Loading playlist...</div>;
  }

  // Map track download statuses
  const trackStatuses = items.reduce((acc, { track }) => {
    if (!track || (track as any).id === undefined) return acc;
    const t = track as LibrespotTrackType;
    const qi = queueItems.find(item => item.downloadType === "track" && item.spotifyId === t.id);
    acc[t.id] = qi ? getStatus(qi) : null;
    return acc;
  }, {} as Record<string, string | null>);

  const filteredItems = items.filter(({ track }) => {
    const t = track as LibrespotTrackType | LibrespotPlaylistTrackStubType | null;
    if (!t || (t as any).id === undefined) return false;
    const full = t as LibrespotTrackType;
    if (settings?.explicitFilter && full.explicit) return false;
    return true;
  });

  return (
    <div className="space-y-4 md:space-y-6">
      {/* Back Button */}
      <div className="mb-4 md:mb-6">
        <button
          onClick={() => window.history.back()}
          className="flex items-center gap-2 p-2 -ml-2 text-sm font-semibold text-content-secondary dark:text-content-secondary-dark hover:text-content-primary dark:hover:text-content-primary-dark hover:bg-surface-muted dark:hover:bg-surface-muted-dark rounded-lg transition-all"
        >
          <FaArrowLeft className="icon-secondary hover:icon-primary" />
          <span>Back to results</span>
        </button>
      </div>
      
      {/* Playlist Header - Mobile Optimized */}
      <div className="bg-surface dark:bg-surface-dark border border-border dark:border-border-dark rounded-xl p-4 md:p-6 shadow-sm">
        <div className="flex flex-col items-center gap-4 md:gap-6">
          {playlistMetadata.picture ? (
            <img
              src={playlistMetadata.picture}
              alt={playlistMetadata.name}
              className="w-32 h-32 sm:w-40 sm:h-40 md:w-48 md:h-48 object-cover rounded-lg shadow-lg mx-auto"
            />
          ) : (
            <div
              className="w-32 h-32 sm:w-40 sm:h-40 md:w-48 md:h-48 rounded-lg shadow-lg mx-auto overflow-hidden bg-surface-muted dark:bg-surface-muted-dark grid grid-cols-2 grid-rows-2"
            >
              {(Array.from(
                new Map(
                  filteredItems
                    .map(({ track }) => (track as any)?.album?.images?.at(-1)?.url)
                    .filter((u) => !!u)
                    .map((u) => [u, u] as const)
                ).values()
              ) as string[]).slice(0, 4).map((url, i) => (
                <img
                  key={`${url}-${i}`}
                  src={url}
                  alt={`Cover ${i + 1}`}
                  className="w-full h-full object-cover"
                />
              ))}
              {filteredItems.length === 0 && (
                <img
                  src="/placeholder.jpg"
                  alt={playlistMetadata.name}
                  className="col-span-2 row-span-2 w-full h-full object-cover"
                />
              )}
            </div>
          )}
          <div className="flex-grow space-y-2 text-center">
            <h1 className="text-2xl md:text-3xl font-bold text-content-primary dark:text-content-primary-dark leading-tight">{playlistMetadata.name}</h1>
            {playlistMetadata.description && (
              <p className="text-base md:text-lg text-content-secondary dark:text-content-secondary-dark">{playlistMetadata.description}</p>
            )}
            <p className="text-sm text-content-muted dark:text-content-muted-dark">
              By {playlistMetadata.owner.display_name} • {totalTracks} songs
            </p>
          </div>
        </div>
        
        {/* Action Buttons - Full Width on Mobile */}
        <div className="mt-4 md:mt-6 flex flex-col sm:flex-row gap-2 sm:gap-3">
          <button
            onClick={handleDownloadPlaylist}
            disabled={!!playlistQueueItem && playlistStatus !== "error"}
            className="flex-1 px-6 py-3 bg-button-primary hover:bg-button-primary-hover text-button-primary-text rounded-lg transition-all font-semibold shadow-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {playlistStatus
              ? playlistStatus === "queued"
                ? "Queued."
                : playlistStatus === "error"
                ? "Download All"
                : <img src="/spinner.svg" alt="Loading" className="w-5 h-5 animate-spin inline-block" />
              : "Download All"}
          </button>
          {settings?.watch?.enabled && (
            <button
              onClick={handleToggleWatch}
              className={`flex items-center justify-center gap-2 px-6 py-3 rounded-lg transition-all font-semibold shadow-sm ${
                isWatched
                  ? "bg-error hover:bg-error-hover text-button-primary-text"
                  : "bg-surface-muted dark:bg-surface-muted-dark hover:bg-surface-accent dark:hover:bg-surface-accent-dark text-content-primary dark:text-content-primary-dark"
              }`}
            >
              <img
                src={isWatched ? "/eye-crossed.svg" : "/eye.svg"}
                alt="Watch status"
                className={`w-5 h-5 ${isWatched ? "icon-inverse" : "logo"}`}
              />
              {isWatched ? "Unwatch" : "Watch"}
            </button>
          )}
        </div>
      </div>

      {/* Tracks Section */}
      <div className="space-y-3 md:space-y-4">
        <div className="flex items-center justify_between px-1">
          <h2 className="text-xl font-semibold text-content-primary dark:text-content-primary-dark">Tracks</h2>
          {items.length > 0 && (
            <span className="text-sm text-content-muted dark:text-content-muted-dark">
              Showing {items.length} of {totalTracks} tracks
            </span>
          )}
        </div>
        
        <div className="bg-surface-muted dark:bg-surface-muted-dark rounded-xl p-2 md:p-4 shadow-sm">
          <div className="space-y-1 md:space-y-2">
            {filteredItems.map(({ track }, index) => {
              const t = track as LibrespotTrackType;
              if (!t || !t.id) return null;
              return (
                <div
                  key={`${t.id}-${index}`}
                  className="flex items-center justify-between p-3 md:p-4 hover:bg-surface-secondary dark:hover:bg-surface-secondary-dark rounded-lg transition-colors duration-200 group"
                >
                  <div className="flex items-center gap-3 md:gap-4 min-w-0 flex-1">
                    <span className="text-content-muted dark:text-content-muted-dark w-6 md:w-8 text-right text-sm font-medium">{index + 1}</span>
                    <Link to="/album/$albumId" params={{ albumId: t.album.id }}>
                      <img
                        src={t.album.images?.at(-1)?.url || "/placeholder.jpg "}
                        alt={t.album.name}
                        className="w-10 h-10 md:w-12 md:h-12 object-cover rounded hover:scale-105 transition-transform duration-300"
                      />
                    </Link>
                    <div className="min-w-0 flex-1">
                      <Link to="/track/$trackId" params={{ trackId: t.id }} className="font-medium text-content-primary dark:text-content-primary-dark text-sm md:text-base hover:underline block truncate">
                        {t.name}
                      </Link>
                      <p className="text-xs md:text-sm text-content-secondary dark:text-content-secondary-dark truncate">
                        {t.artists.map((artist, index) => (
                          <span key={artist.id}>
                            <Link
                              to="/artist/$artistId"
                              params={{ artistId: artist.id }}
                              className="hover:underline"
                            >
                              {artist.name}
                            </Link>
                            {index < t.artists.length - 1 && ", "}
                          </span>
                        ))}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 md:gap-4 shrink-0">
                    <span className="text-content-muted dark:text-content-muted-dark text-xs md:text-sm hidden sm:block">
                      {Math.floor(t.duration_ms / 60000)}:
                      {((t.duration_ms % 60000) / 1000).toFixed(0).padStart(2, "0")}
                    </span>
                    <button
                      onClick={() => handleDownloadTrack(t)}
                      disabled={!!trackStatuses[t.id] && trackStatuses[t.id] !== "error"}
                      className="w-9 h-9 md:w-10 md:h-10 flex items-center justify-center bg-surface-muted dark:bg-surface-muted-dark hover:bg-surface-accent dark:hover:bg-surface-accent-dark border border-border-muted dark:border-border-muted-dark hover:border-border-accent dark:hover:border-border-accent-dark rounded-full transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                      title={
                        trackStatuses[t.id]
                          ? trackStatuses[t.id] === "queued"
                            ? "Queued."
                            : trackStatuses[t.id] === "error"
                            ? "Download"
                            : "Downloading..."
                          : "Download"
                      }
                    >
                      {trackStatuses[t.id]
                        ? trackStatuses[t.id] === "queued"
                          ? "Queued."
                          : trackStatuses[t.id] === "error"
                          ? <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
                          : <img src="/spinner.svg" alt="Loading" className="w-4 h-4 animate-spin" />
                        : <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
                      }
                    </button>
                  </div>
                </div>
              );
            })}
            
            {/* Loading indicator */}
            {loadingTracks && (
              <div className="flex justify-center py-4">
                <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
              </div>
            )}
            
            {/* Intersection observer target */}
            {hasMoreTracks && (
              <div ref={loadingRef} className="h-4" />
            )}
            
            {/* End of tracks indicator */}
            {!hasMoreTracks && items.length > 0 && (
              <div className="text-center py-4 text-content-muted dark:text-content-muted-dark">
                All tracks loaded
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
