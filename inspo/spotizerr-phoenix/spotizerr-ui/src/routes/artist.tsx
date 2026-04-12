import { Link, useParams } from "@tanstack/react-router";
import { useEffect, useState, useContext, useRef, useCallback } from "react";
import { toast } from "sonner";
import apiClient from "../lib/api-client";
import type { LibrespotAlbumType, LibrespotArtistType, LibrespotTrackType } from "@/types/librespot";
import { QueueContext, getStatus } from "../contexts/queue-context";
import { useSettings } from "../contexts/settings-context";
import { FaArrowLeft, FaBookmark, FaRegBookmark, FaDownload } from "react-icons/fa";
import { AlbumCard } from "../components/AlbumCard";

export const Artist = () => {
  const { artistId } = useParams({ from: "/artist/$artistId" });
  const [artist, setArtist] = useState<LibrespotArtistType | null>(null);
  const [artistAlbums, setArtistAlbums] = useState<LibrespotAlbumType[]>([]);
  const [artistSingles, setArtistSingles] = useState<LibrespotAlbumType[]>([]);
  const [artistCompilations, setArtistCompilations] = useState<LibrespotAlbumType[]>([]);
  const [artistAppearsOn, setArtistAppearsOn] = useState<LibrespotAlbumType[]>([]);
  const [topTracks, setTopTracks] = useState<LibrespotTrackType[]>([]);
  const [bannerUrl, setBannerUrl] = useState<string | null>(null);
  const [isWatched, setIsWatched] = useState(false);
  const [artistStatus, setArtistStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const context = useContext(QueueContext);
  const { settings } = useSettings();

  const sentinelRef = useRef<HTMLDivElement | null>(null);

  // Pagination state - using refs for synchronous offset tracking
  const ALBUM_BATCH = 12;
  const albumOffsetRef = useRef<number>(0);
  const singleOffsetRef = useRef<number>(0);
  const compOffsetRef = useRef<number>(0);
  const appearsOffsetRef = useRef<number>(0);
  const [loading, setLoading] = useState<boolean>(false);
  const [loadingMore, setLoadingMore] = useState<boolean>(false);
  const loadingMoreRef = useRef(false);
  const initialLoadCompleteRef = useRef(false);
  const loadMoreFnRef = useRef<(() => Promise<void>) | null>(null);
  const [hasMore, setHasMore] = useState<boolean>(true); // assume more until we learn otherwise

  if (!context) {
    throw new Error("useQueue must be used within a QueueProvider");
  }
  const { addItem, items } = context;

  // Preload commonly used icons ASAP (before first buttons need them)
  useEffect(() => {
    const i = new Image();
    i.src = "/download.svg";
    return () => { /* no-op */ };
  }, []);

  // Track queue status mapping
  const trackStatuses = topTracks.reduce((acc, t) => {
    const qi = items.find(item => item.downloadType === "track" && item.spotifyId === t.id);
    acc[t.id] = qi ? getStatus(qi) : null;
    return acc;
  }, {} as Record<string, string | null>);
  
  // Helper: fetch a batch of albums by ids
  const fetchAlbumsByIds = useCallback(async (ids: string[]): Promise<LibrespotAlbumType[]> => {
    const results = await Promise.all(
      ids.map((id) => apiClient.get<LibrespotAlbumType>(`/album/info?id=${id}`).then(r => r.data).catch(() => null))
    );
    return results.filter(Boolean) as LibrespotAlbumType[];
  }, []);

  // Fetch artist info & first page of albums
  useEffect(() => {
    if (!artistId) return;

    let cancelled = false;

    const fetchInitial = async () => {
      setLoading(true);
      setError(null);
      setArtistAlbums([]);
      setArtistSingles([]);
      setArtistCompilations([]);
      setArtistAppearsOn([]);
      albumOffsetRef.current = 0;
      singleOffsetRef.current = 0;
      compOffsetRef.current = 0;
      appearsOffsetRef.current = 0;
      setHasMore(true);
      setBannerUrl(null); // reset hero; will lazy-load below
      loadingMoreRef.current = false;
      initialLoadCompleteRef.current = false;

      try {
        const resp = await apiClient.get<LibrespotArtistType>(`/artist/info?id=${artistId}`);
        const data: LibrespotArtistType = resp.data;

        if (cancelled) return;

        if (data?.id && data?.name) {
          // set artist meta
          setArtist(data);

          // Lazy-load banner image after render
          const allImages = [...(data.portrait_group.image ?? []), ...(data.biography?.[0].portrait_group?.image ?? [])];
          const candidateBanner = allImages
            .filter(img => img && typeof img === 'object' && 'url' in img)
            .sort((a, b) => (b.width ?? 0) - (a.width ?? 0))[0]?.url || "/placeholder.jpg";
          // Use async preload to avoid blocking initial paint
          setTimeout(() => {
            const img = new Image();
            img.src = candidateBanner;
            img.onload = () => { if (!cancelled) setBannerUrl(candidateBanner); };
          }, 0);

          // top tracks (if provided)
          const topTrackIds = Array.isArray(data.top_track) && data.top_track.length > 0
            ? data.top_track[0].track.slice(0, 10)
            : [];
          if (topTrackIds.length) {
            const tracksFull = await Promise.all(
              topTrackIds.map((id) => apiClient.get<LibrespotTrackType>(`/track/info?id=${id}`).then(r => r.data).catch(() => null))
            );
            if (!cancelled) setTopTracks(tracksFull.filter(Boolean) as LibrespotTrackType[]);
          } else {
            if (!cancelled) setTopTracks([]);
          }

          // Progressive album loading: album -> single -> compilation -> appears_on
          const albumIds = data.album_group ?? [];
          const singleIds = data.single_group ?? [];
          const compIds = data.compilation_group ?? [];
          const appearsIds = data.appears_on_group ?? [];

          // Determine initial number based on screen size: 4 on small screens
          const isSmallScreen = typeof window !== "undefined" && !window.matchMedia("(min-width: 640px)").matches;
          const initialTarget = isSmallScreen ? 4 : ALBUM_BATCH;

          // Load initial sets from each group in order until initialTarget reached
          let aOff = 0, sOff = 0, cOff = 0, apOff = 0;
          let loaded = 0;
          let aList: LibrespotAlbumType[] = [];
          let sList: LibrespotAlbumType[] = [];
          let cList: LibrespotAlbumType[] = [];
          let apList: LibrespotAlbumType[] = [];

          if (albumIds.length > 0 && loaded < initialTarget) {
            const take = albumIds.slice(0, initialTarget - loaded);
            aList = await fetchAlbumsByIds(take);
            aOff = take.length;
            loaded += aList.length;
          }
          if (singleIds.length > 0 && loaded < initialTarget) {
            const take = singleIds.slice(0, initialTarget - loaded);
            sList = await fetchAlbumsByIds(take);
            sOff = take.length;
            loaded += sList.length;
          }
          if (compIds.length > 0 && loaded < initialTarget) {
            const take = compIds.slice(0, initialTarget - loaded);
            cList = await fetchAlbumsByIds(take);
            cOff = take.length;
            loaded += cList.length;
          }
          if (appearsIds.length > 0 && loaded < initialTarget) {
            const take = appearsIds.slice(0, initialTarget - loaded);
            apList = await fetchAlbumsByIds(take);
            apOff = take.length;
            loaded += apList.length;
          }

          if (!cancelled) {
            setArtistAlbums(aList);
            setArtistSingles(sList);
            setArtistCompilations(cList);
            setArtistAppearsOn(apList);
            // Store offsets in refs for next loads
            albumOffsetRef.current = aOff;
            singleOffsetRef.current = sOff;
            compOffsetRef.current = cOff;
            appearsOffsetRef.current = apOff;
            // Determine if more remain
            setHasMore((albumIds.length > aOff) || (singleIds.length > sOff) || (compIds.length > cOff) || (appearsIds.length > apOff));
            // Mark initial load complete
            initialLoadCompleteRef.current = true;
          }
        } else {
          setError("Could not load artist data.");
        }

        // fetch watch status
        try {
          const watchStatusResponse = await apiClient.get<{ is_watched: boolean }>(`/artist/watch/${artistId}/status`);
          if (!cancelled) setIsWatched(watchStatusResponse.data.is_watched);
        } catch (e) {
          // ignore watch status errors
          console.warn("Failed to load watch status", e);
        }
      } catch (err) {
        if (!cancelled) {
          console.error(err);
          setError("Failed to load artist page");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    fetchInitial();

    return () => {
      cancelled = true;
    };
  }, [artistId, fetchAlbumsByIds]);

  // Fetch more albums (next page)
  const fetchMoreAlbums = useCallback(async () => {
    // Use ref to prevent concurrent calls (state updates are async)
    if (!artistId || loadingMoreRef.current || loading || !hasMore || !artist) return;
    
    // Read offsets from refs synchronously to get the most current values
    let aOff = albumOffsetRef.current;
    let sOff = singleOffsetRef.current;
    let cOff = compOffsetRef.current;
    let apOff = appearsOffsetRef.current;
    
    loadingMoreRef.current = true;
    setLoadingMore(true);

    try {
      // Deduplicate source IDs
      const albumIds = [...new Set(artist.album_group ?? [])];
      const singleIds = [...new Set(artist.single_group ?? [])];
      const compIds = [...new Set(artist.compilation_group ?? [])];
      const appearsIds = [...new Set(artist.appears_on_group ?? [])];

      const nextA: LibrespotAlbumType[] = [];
      const nextS: LibrespotAlbumType[] = [];
      const nextC: LibrespotAlbumType[] = [];
      const nextAp: LibrespotAlbumType[] = [];

      const totalLoaded = () => nextA.length + nextS.length + nextC.length + nextAp.length;

      if (aOff < albumIds.length && totalLoaded() < ALBUM_BATCH) {
        const remaining = ALBUM_BATCH - totalLoaded();
        const take = albumIds.slice(aOff, aOff + remaining);
        nextA.push(...(await fetchAlbumsByIds(take)));
        aOff += take.length;
      }
      if (sOff < singleIds.length && totalLoaded() < ALBUM_BATCH) {
        const remaining = ALBUM_BATCH - totalLoaded();
        const take = singleIds.slice(sOff, sOff + remaining);
        nextS.push(...(await fetchAlbumsByIds(take)));
        sOff += take.length;
      }
      if (cOff < compIds.length && totalLoaded() < ALBUM_BATCH) {
        const remaining = ALBUM_BATCH - totalLoaded();
        const take = compIds.slice(cOff, cOff + remaining);
        nextC.push(...(await fetchAlbumsByIds(take)));
        cOff += take.length;
      }
      if (apOff < appearsIds.length && totalLoaded() < ALBUM_BATCH) {
        const remaining = ALBUM_BATCH - totalLoaded();
        const take = appearsIds.slice(apOff, apOff + remaining);
        nextAp.push(...(await fetchAlbumsByIds(take)));
        apOff += take.length;
      }

      // Append new items
      setArtistAlbums((cur) => [...cur, ...nextA]);
      setArtistSingles((cur) => [...cur, ...nextS]);
      setArtistCompilations((cur) => [...cur, ...nextC]);
      setArtistAppearsOn((cur) => [...cur, ...nextAp]);

      // Update refs with new offsets
      albumOffsetRef.current = aOff;
      singleOffsetRef.current = sOff;
      compOffsetRef.current = cOff;
      appearsOffsetRef.current = apOff;

      setHasMore((albumIds.length > aOff) || (singleIds.length > sOff) || (compIds.length > cOff) || (appearsIds.length > apOff));
    } catch (err) {
      console.error("Failed to load more albums", err);
      toast.error("Failed to load more albums");
      setHasMore(false);
    } finally {
      loadingMoreRef.current = false;
      setLoadingMore(false);
    }
  }, [artistId, loading, hasMore, artist, fetchAlbumsByIds]);

  // Keep loadMoreFnRef updated with latest fetchMoreAlbums
  loadMoreFnRef.current = fetchMoreAlbums;

  // IntersectionObserver to trigger fetchMoreAlbums when sentinel is visible
  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel) return;
    if (!hasMore) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting && !loadingMoreRef.current && loadMoreFnRef.current) {
            loadMoreFnRef.current();
          }
        });
      },
      {
        root: null,
        rootMargin: "400px", // start loading a bit before the sentinel enters viewport
        threshold: 0.1,
      }
    );

    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore]);

  // Auto progressive loading regardless of scroll
  // Only runs after initial load is complete to prevent race condition
  useEffect(() => {
    if (!artist || !hasMore || loading) return;
    if (!initialLoadCompleteRef.current) return;
    if (loadingMoreRef.current) return;
    
    const t = setTimeout(() => {
      if (!loadingMoreRef.current && loadMoreFnRef.current) {
        loadMoreFnRef.current();
      }
    }, 350);
    return () => clearTimeout(t);
  }, [artist, hasMore, loading, artistAlbums.length, artistSingles.length, artistCompilations.length, artistAppearsOn.length]);

  // --- existing handlers (unchanged) ---
  const handleDownloadTrack = (track: LibrespotTrackType) => {
    if (!track.id) return;
    toast.info(`Adding ${track.name} to queue...`);
    addItem({ spotifyId: track.id, type: "track", name: track.name });
  };

  const handleDownloadAlbum = (album: LibrespotAlbumType) => {
    toast.info(`Adding ${album.name} to queue...`);
    addItem({ spotifyId: album.id, type: "album", name: album.name });
  };

  const handleDownloadArtist = async () => {
    setArtistStatus("downloading");
    if (!artistId || !artist) return;

    try {
      toast.info(`Downloading ${artist.name} discography...`);

      // Call the artist download endpoint which returns album task IDs
      const response = await apiClient.get(`/artist/download/${artistId}`);

      if (response.data.queued_albums?.length > 0) {
        setArtistStatus("queued");
        toast.success(`${artist.name} discography queued successfully!`, {
          description: `${response.data.queued_albums.length} albums added to queue.`,
        });
      } else {
        setArtistStatus(null);
        toast.info("No new albums to download for this artist.");
      }
    } catch (error: any) {
      setArtistStatus("error");
      console.error("Artist download failed:", error);
      toast.error("Failed to download artist", {
        description: error.response?.data?.error || "An unexpected error occurred.",
      });
    }
  };

  const handleDownloadGroup = async (group: "album" | "single" | "compilation" | "appears_on") => {
    if (!artistId || !artist) return;
    try {
      toast.info(`Queueing ${group} downloads for ${artist.name}...`);
      const response = await apiClient.get(`/artist/download/${artistId}?album_type=${group}`);
      const count = response.data?.queued_albums?.length ?? 0;
      if (count > 0) {
        toast.success(`Queued ${count} ${group}${count > 1 ? "s" : ""}.`);
      } else {
        toast.info(`No new ${group} releases to download.`);
      }
    } catch (error: any) {
      console.error(`Failed to queue ${group} downloads:`, error);
      toast.error(`Failed to queue ${group} downloads`, {
        description: error.response?.data?.error || "An unexpected error occurred.",
      });
    }
  };

  const handleToggleWatch = async () => {
    if (!artistId || !artist) return;
    try {
      if (isWatched) {
        await apiClient.delete(`/artist/watch/${artistId}`);
        toast.success(`Removed ${artist.name} from watchlist.`);
      } else {
        await apiClient.put(`/artist/watch/${artistId}`);
        toast.success(`Added ${artist.name} to watchlist.`);
      }
      setIsWatched(!isWatched);
    } catch (err) {
      toast.error("Failed to update watchlist.");
      console.error(err);
    }
  };

  if (error) {
    return <div className="text-red-500">{error}</div>;
  }

  if (loading && !artist) {
    return <div>Loading...</div>;
  }

  if (!artist) {
    return <div>Artist data could not be fully loaded. Please try again later.</div>;
  }

  return (
    <div className="artist-page">
      <div className="mb-4 md:mb-6">
        <button
          onClick={() => window.history.back()}
          className="flex items-center gap-2 p-2 -ml-2 text-sm font-semibold text-content-secondary dark:text-content-secondary-dark hover:text-content-primary dark:hover:text-content-primary-dark hover:bg-surface-muted dark:hover:bg-surface-muted-dark rounded-lg transition-all"
        >
          <FaArrowLeft className="icon-secondary hover:icon-primary" />
          <span>Back to results</span>
        </button>
      </div>

      {/* Hero banner using highest resolution image (lazy-loaded) */}
      <div
        className="relative mb-8 rounded-xl overflow-hidden h-56 sm:h-64 md:h-80 lg:h-[420px] bg-surface-accent dark:bg-surface-accent-dark"
        style={bannerUrl ? { backgroundImage: `url(${bannerUrl})`, backgroundSize: "cover", backgroundPosition: "center" } : undefined}
      >
        <div className="absolute inset-0 bg-gradient-to-b from-black/30 via-black/50 to-black/80" />
        <div className="absolute inset-x-0 bottom-0 p-4 md:p-6 flex flex-col gap-3 text-white">
          <h1 className="text-4xl md:text-6xl font-extrabold tracking-tight leading-none">{artist.name}</h1>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={handleDownloadArtist}
              disabled={artistStatus === "downloading" || artistStatus === "queued"}
              className="flex items-center gap-2 px-4 py-2 bg-button-success hover:bg-button-success-hover text-button-success-text rounded-md transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
              title={
                artistStatus === "downloading"
                  ? "Downloading..."
                  : artistStatus === "queued"
                  ? "Queued."
                  : "Download All"
              }
            >
              {artistStatus
                ? artistStatus === "queued"
                  ? "Queued."
                  : artistStatus === "downloading"
                  ? <img src="/spinner.svg" alt="Loading" className="w-5 h-5 animate-spin" />
                  : <>
                      <FaDownload className="icon-inverse" />
                      <span>Download All</span>
                    </>
                : <>
                    <FaDownload className="icon-inverse" />
                    <span>Download All</span>
                  </>
              }
            </button>
            {settings?.watch?.enabled && (
              <button
                onClick={handleToggleWatch}
                className={`flex items-center gap-2 px-4 py-2 rounded-md transition-colors border ${isWatched
                    ? "bg-button-primary text-button-primary-text border-primary"
                    : "bg-surface dark:bg-surface-dark hover:bg-surface-muted dark:hover:bg-surface-muted-dark border-border dark:border-border-dark text-content-primary dark:text-content-primary-dark"
                  }`}
              >
                {isWatched ? (
                  <>
                    <FaBookmark className="icon-inverse" />
                    <span>Watching</span>
                  </>
                ) : (
                  <>
                    <FaRegBookmark className="icon-primary" />
                    <span>Watch</span>
                  </>
                )}
              </button>
            )}
          </div>
        </div>
      </div>

      {topTracks.length > 0 && (
        <div className="mb-12">
          <h2 className="text-3xl font-bold mb-6 text-content-primary dark:text-content-primary-dark">Top Tracks</h2>
          <div className="track-list space-y-2">
            {topTracks.map((track, index) => (
              <div
                key={track.id}
                className={`track-item flex items-center justify-between p-2 rounded-md hover:bg-surface-muted dark:hover:bg-surface-muted-dark transition-colors ${index >= 5 ? "hidden sm:flex" : ""}`}
              >
                <Link
                  to="/track/$trackId"
                  params={{ trackId: track.id }}
                  className="font-semibold text-content-primary dark:text-content-primary-dark"
                >
                  {track.name}
                </Link>
                <button
                  onClick={() => handleDownloadTrack(track)}
                  disabled={!!trackStatuses[track.id] && trackStatuses[track.id] !== "error"}
                  className="w-9 h-9 md:w-10 md:h-10 flex items-center justify-center bg-surface-muted dark:bg-surface-muted-dark hover:bg-surface-accent dark:hover:bg-surface-accent-dark border border-border-muted dark:border-border-muted-dark hover:border-border-accent dark:hover:border-border-accent-dark rounded-full transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  title={
                    trackStatuses[track.id]
                      ? trackStatuses[track.id] === "queued"
                        ? "Queued."
                        : trackStatuses[track.id] === "error"
                        ? "Download"
                        : "Downloading..."
                      : "Download"
                  }
                >
                  {trackStatuses[track.id]
                    ? trackStatuses[track.id] === "queued"
                      ? "Queued."
                      : trackStatuses[track.id] === "error"
                      ? <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
                      : <img src="/spinner.svg" alt="Loading" className="w-4 h-4 animate-spin" />
                    : <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
                  }
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Albums */}
      {artistAlbums.length > 0 && (
        <div className="mb-12">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-3xl font-bold text-content-primary dark:text-content-primary-dark">Albums</h2>
            <button
              onClick={() => handleDownloadGroup("album")}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-button-success hover:bg-button-success-hover text-button-success-text rounded-md transition-colors"
              title="Download all albums"
            >
              <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
              <span>Download</span>
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
            {artistAlbums.map((album) => (
              <AlbumCard key={album.id} album={album} onDownload={() => handleDownloadAlbum(album)} />
            ))}
          </div>
        </div>
      )}

      {/* Singles */}
      {artistSingles.length > 0 && (
        <div className="mb-12">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-3xl font-bold text-content-primary dark:text-content-primary-dark">Singles</h2>
            <button
              onClick={() => handleDownloadGroup("single")}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-button-success hover:bg-button-success-hover text-button-success-text rounded-md transition-colors"
              title="Download all singles"
            >
              <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
              <span>Download</span>
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
            {artistSingles.map((album) => (
              <AlbumCard key={album.id} album={album} onDownload={() => handleDownloadAlbum(album)} />
            ))}
          </div>
        </div>
      )}

      {/* Compilations */}
      {artistCompilations.length > 0 && (
        <div className="mb-12">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-3xl font-bold text-content-primary dark:text-content-primary-dark">Compilations</h2>
            <button
              onClick={() => handleDownloadGroup("compilation")}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-button-success hover:bg-button-success-hover text-button-success-text rounded-md transition-colors"
              title="Download all compilations"
            >
              <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
              <span>Download</span>
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
            {artistCompilations.map((album) => (
              <AlbumCard key={album.id} album={album} onDownload={() => handleDownloadAlbum(album)} />
            ))}
          </div>
        </div>
      )}

      {/* Appears On */}
      {artistAppearsOn.length > 0 && (
        <div className="mb-12">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-3xl font-bold text-content-primary dark:text-content-primary-dark">Appears On</h2>
            <button
              onClick={() => handleDownloadGroup("appears_on")}
              className="flex items-center gap-2 px-3 py-1.5 text-sm bg-button-success hover:bg-button-success-hover text-button-success-text rounded-md transition-colors"
              title="Download all appears on"
            >
              <img src="/download.svg" alt="Download" className="w-4 h-4 logo" />
              <span>Download</span>
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6">
            {artistAppearsOn.map((album) => (
              <AlbumCard key={album.id} album={album} onDownload={() => handleDownloadAlbum(album)} />
            ))}
          </div>
        </div>
      )}

      {/* sentinel + loading */}
      <div className="flex flex-col items-center gap-2">
        {loadingMore && <div className="py-4">Loading more...</div>}
        {!hasMore && !loading && <div className="py-4 text-sm text-content-secondary">End of discography</div>}
        {/* fallback load more button for browsers that block IntersectionObserver or for manual control */}
        {hasMore && !loadingMore && (
          <button
            onClick={() => fetchMoreAlbums()}
            className="px-4 py-2 mb-6 rounded"
          >
            Loading...
          </button>
        )}
        <div ref={sentinelRef} style={{ height: 1, width: "100%" }} />
      </div>
    </div>
  );
};
