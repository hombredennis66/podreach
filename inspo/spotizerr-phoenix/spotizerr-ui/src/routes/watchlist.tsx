import { useState, useEffect, useCallback } from "react";
import apiClient from "../lib/api-client";
import { toast } from "sonner";
import { useSettings } from "../contexts/settings-context";
import { Link } from "@tanstack/react-router";
import type { LibrespotArtistType, LibrespotPlaylistType } from "../types/librespot";
import { FaRegTrashAlt, FaSearch } from "react-icons/fa";

// --- Type Definitions ---
interface BaseWatched {
  itemType: "artist" | "playlist";
  spotify_id: string;
}
type WatchedArtist = LibrespotArtistType & { itemType: "artist" };
type WatchedPlaylist = LibrespotPlaylistType & { itemType: "playlist" };

type WatchedItem = WatchedArtist | WatchedPlaylist;

export const Watchlist = () => {
  const { settings, isLoading: settingsLoading } = useSettings();
  const [items, setItems] = useState<WatchedItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [expectedCount, setExpectedCount] = useState<number | null>(null);

  // Utility to batch fetch details
  async function batchFetch<T>(
    ids: string[],
    fetchFn: (id: string) => Promise<T>,
    batchSize: number,
    onBatch: (results: T[]) => void
  ) {
    for (let i = 0; i < ids.length; i += batchSize) {
      const batchIds = ids.slice(i, i + batchSize);
      const batchResults = await Promise.all(
        batchIds.map((id) => fetchFn(id).catch(() => null))
      );
      onBatch(batchResults.filter(Boolean) as T[]);
    }
  }

  const fetchWatchlist = useCallback(async () => {
    setIsLoading(true);
    setItems([]); // Clear previous items
    setExpectedCount(null);
    try {
      const [artistsRes, playlistsRes] = await Promise.all([
        apiClient.get<BaseWatched[]>("/artist/watch/list"),
        apiClient.get<BaseWatched[]>("/playlist/watch/list"),
      ]);

      // Prepare lists of IDs
      const artistIds = artistsRes.data.map((artist) => artist.spotify_id);
      const playlistIds = playlistsRes.data.map((playlist) => playlist.spotify_id);
      setExpectedCount(artistIds.length + playlistIds.length);

      // Allow UI to render grid and skeletons immediately
      setIsLoading(false);

      // Helper to update state incrementally
      const appendItems = (newItems: WatchedItem[]) => {
        setItems((prev) => [...prev, ...newItems]);
      };

      // Fetch artist details in batches
      await batchFetch<LibrespotArtistType>(
        artistIds,
        (id) => apiClient.get<LibrespotArtistType>(`/artist/info?id=${id}`).then(res => res.data),
        5, // batch size
        (results) => {
          const items: WatchedArtist[] = results.map((data) => ({
            ...data,
            itemType: "artist",
          }));
          appendItems(items);
        }
      );

      // Fetch playlist details in batches
      await batchFetch<LibrespotPlaylistType>(
        playlistIds,
        (id) => apiClient.get<LibrespotPlaylistType>(`/playlist/info?id=${id}`).then(res => res.data),
        5, // batch size
        (results) => {
          const items: WatchedPlaylist[] = results.map((data) => ({
            ...data,
            itemType: "playlist",
            spotify_id: data.id,
          }));
          appendItems(items);
        }
      );
    } catch {
      toast.error("Failed to load watchlist.");
    }
  }, []);

  useEffect(() => {
    if (!settingsLoading && settings?.watch?.enabled) {
      fetchWatchlist();
    } else if (!settingsLoading) {
      setIsLoading(false);
    }
  }, [settings, settingsLoading, fetchWatchlist]);

  const handleUnwatch = async (item: WatchedItem) => {
    toast.promise(apiClient.delete(`/${item.itemType}/watch/${item.id}`), {
      loading: `Unwatching ${item.name}...`,
      success: () => {
        setItems((prev) => prev.filter((i) => i.id !== item.id));
        return `${item.name} has been unwatched.`;
      },
      error: `Failed to unwatch ${item.name}.`,
    });
  };

  const handleCheck = async (item: WatchedItem) => {
    toast.promise(apiClient.post(`/${item.itemType}/watch/trigger_check/${item.id}`), {
      loading: `Checking ${item.name} for updates...`,
      success: (res: { data: { message?: string } }) => res.data.message || `Check triggered for ${item.name}.`,
      error: `Failed to trigger check for ${item.name}.`,
    });
  };

  const handleCheckAll = () => {
    toast.promise(
      Promise.all([apiClient.post("/artist/watch/trigger_check"), apiClient.post("/playlist/watch/trigger_check")]),
      {
        loading: "Triggering checks for all watched items...",
        success: "Successfully triggered checks for all items.",
        error: "Failed to trigger one or more checks.",
      },
    );
  };

  if (isLoading || settingsLoading) {
    return <div className="text-center text-content-muted dark:text-content-muted-dark">Loading Watchlist...</div>;
  }

  if (!settings?.watch?.enabled) {
    return (
      <div className="text-center p-8">
        <h2 className="text-2xl font-bold mb-2 text-content-primary dark:text-content-primary-dark">Watchlist Disabled</h2>
        <p className="text-content-secondary dark:text-content-secondary-dark">The watchlist feature is currently disabled. You can enable it in the settings.</p>
        <Link to="/config" className="text-primary hover:underline mt-4 inline-block">
          Go to Settings
        </Link>
      </div>
    );
  }

  // Show "empty" only if not loading and nothing expected
  if (!isLoading && items.length === 0 && (!expectedCount || expectedCount === 0)) {
    return (
      <div className="text-center p-8">
        <h2 className="text-2xl font-bold mb-2 text-content-primary dark:text-content-primary-dark">Watchlist is Empty</h2>
        <p className="text-content-secondary dark:text-content-secondary-dark">Start watching artists or playlists to see them here.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center">
        <h1 className="text-3xl font-bold text-content-primary dark:text-content-primary-dark">Watched Artists & Playlists</h1>
        <button
          onClick={handleCheckAll}
          className="px-4 py-2 bg-button-primary hover:bg-button-primary-hover text-button-primary-text rounded-md flex items-center gap-2"
        >
          <FaSearch className="icon-inverse" /> Check All
        </button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
      {items.map((item) => (
          <div key={item.id} className="bg-surface dark:bg-surface-secondary-dark p-4 rounded-lg shadow space-y-2 flex flex-col">
            <a href={`/${item.itemType}/${item.id}`} className="flex-grow">
              <img
                src={
                  item.itemType === "artist"
                    ? (item as WatchedArtist).portrait_group.image[0].url || "/images/placeholder.jpg"
                    : (item as WatchedPlaylist).picture || "/images/placeholder.jpg"
                }
                alt={item.name}
                className="w-full h-auto object-cover rounded-md aspect-square"
              />
              <h3 className="font-bold pt-2 truncate text-content-primary dark:text-content-primary-dark">{item.name}</h3>
              <p className="text-sm text-content-muted dark:text-content-muted-dark capitalize">{item.itemType}</p>
            </a>
            <div className="flex gap-2 pt-2">
              <button
                onClick={() => handleUnwatch(item)}
                className="w-full px-3 py-1.5 text-sm bg-error hover:bg-error-hover text-button-primary-text rounded-md flex items-center justify-center gap-2"
              >
                <FaRegTrashAlt className="icon-inverse" /> Unwatch
              </button>
              <button
                onClick={() => handleCheck(item)}
                className="w-full px-3 py-1.5 text-sm bg-button-secondary hover:bg-button-secondary-hover text-button-secondary-text hover:text-button-secondary-text-hover rounded-md flex items-center justify-center gap-2"
              >
                <FaSearch className="icon-secondary hover:icon-primary" /> Check
              </button>
            </div>
          </div>
        ))}
        {/* Skeletons for loading items */}
        {isLoading && expectedCount && items.length < expectedCount &&
          Array.from({ length: expectedCount - items.length }).map((_, idx) => (
            <div
              key={`skeleton-${idx}`}
              className="bg-surface dark:bg-surface-secondary-dark p-4 rounded-lg shadow space-y-2 flex flex-col animate-pulse"
            >
              <div className="flex-grow">
                <div className="w-full aspect-square bg-gray-200 dark:bg-gray-700 rounded-md mb-2" />
                <div className="h-5 bg-gray-200 dark:bg-gray-700 rounded w-3/4 mb-1" />
                <div className="h-4 bg-gray-100 dark:bg-gray-800 rounded w-1/2" />
              </div>
              <div className="flex gap-2 pt-2">
                <div className="w-full h-8 bg-gray-200 dark:bg-gray-700 rounded" />
                <div className="w-full h-8 bg-gray-100 dark:bg-gray-800 rounded" />
              </div>
            </div>
          ))
        }
      </div>
    </div>
  );
};
