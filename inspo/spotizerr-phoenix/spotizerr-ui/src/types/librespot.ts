// Librespot wrapper response types for frontend consumption

export interface LibrespotExternalUrls {
  spotify: string;
}

export interface LibrespotImage {
  url: string;
  width: number;
  height: number;
}

export interface LibrespotArtistStub {
  id: string;
  name: string;
  type?: "artist";
  uri?: string;
  external_urls?: LibrespotExternalUrls;
}

export interface LibrespotBiographyType {
  text: string;
  portrait_group: LibrespotArtistImageType;
}

export interface LibrespotTopTrackType {
  country: string;
  track: string[];
}

export interface LibrespotArtistImageType {
  image: LibrespotImage[];
}

// Full artist object (get_artist)
export interface LibrespotArtistType {
  id: string;
  name: string;
  top_track: LibrespotTopTrackType[];
  portrait_group: LibrespotArtistImageType;
  popularity: number;
  biography?: LibrespotBiographyType[];
  album_group?: string[];
  single_group?: string[];
  compilation_group?: string[];
  appears_on_group?: string[];
}

export interface LibrespotCopyright {
  text: string;
  type: string;
}

export type LibrespotReleaseDatePrecision = "day" | "month" | "year";

// Minimal embedded album object returned inside track objects (does not include tracks array)
export interface LibrespotAlbumRef {
  id: string;
  name: string;
  images?: LibrespotImage[];
  release_date?: string;
  release_date_precision?: LibrespotReleaseDatePrecision;
  type?: "album";
  uri?: string;
  album_type?: "album" | "single" | "compilation";
  external_urls?: LibrespotExternalUrls;
  artists?: LibrespotArtistStub[];
}

export interface LibrespotTrackType {
  album: LibrespotAlbumRef;
  artists: LibrespotArtistStub[];
  available_markets?: string[];
  disc_number: number;
  duration_ms: number;
  explicit: boolean;
  external_ids: { isrc?: string };
  external_urls: LibrespotExternalUrls;
  id: string;
  name: string;
  popularity: number;
  track_number: number;
  type: "track";
  uri: string;
  preview_url: string;
  has_lyrics: boolean;
  earliest_live_timestamp: number;
  licensor_uuid: string; // when available
}

export interface LibrespotAlbumType {
  album_type: "album" | "single" | "compilation";
  total_tracks: number;
  external_urls: LibrespotExternalUrls;
  id: string;
  images: LibrespotImage[];
  name: string;
  release_date: string;
  release_date_precision: LibrespotReleaseDatePrecision;
  type: "album";
  uri: string;
  artists: LibrespotArtistStub[];
  // When include_tracks=False -> string[] of base62 IDs
  // When include_tracks=True  -> LibrespotTrackType[]
  tracks: string[] | LibrespotTrackType[];
  copyrights?: LibrespotCopyright[];
  external_ids?: { upc?: string };
  label: string;
  popularity: number;
}

// Playlist types
export interface LibrespotPlaylistOwnerType {
  id: string;
  type: "user";
  uri: string;
  external_urls: LibrespotExternalUrls;
  display_name: string;
}

export interface LibrespotPlaylistTrackStubType {
  id: string;
  uri: string; // spotify:track:{id}
  type: "track";
  external_urls: LibrespotExternalUrls;
}

export interface LibrespotPlaylistItemType {
  added_at: string;
  added_by: LibrespotPlaylistOwnerType;
  is_local: boolean;
  // If expand_items=False -> LibrespotPlaylistTrackStubType
  // If expand_items=True  -> LibrespotTrackType
  track: LibrespotPlaylistTrackStubType | LibrespotTrackType;
  // Additional reference, not a Web API field
  item_id?: string;
}

export interface LibrespotPlaylistTracksPageType {
  offset: number;
  total: number;
  items: LibrespotPlaylistItemType[];
}

export interface LibrespotPlaylistType {
  name: string;
  id: string;
  description: string | null;
  collaborative: boolean;
  owner: LibrespotPlaylistOwnerType;
  snapshot_id: string;
  tracks: LibrespotPlaylistTracksPageType;
  type: "playlist";
  picture: string;
}

// Type guards
export function isAlbumWithExpandedTracks(
  album: LibrespotAlbumType
): album is LibrespotAlbumType & { tracks: LibrespotTrackType[] } {
  const { tracks } = album as LibrespotAlbumType;
  return Array.isArray(tracks) && (tracks.length === 0 || typeof tracks[0] === "object");
}

export function isPlaylistItemWithExpandedTrack(
  item: LibrespotPlaylistItemType
): item is LibrespotPlaylistItemType & { track: LibrespotTrackType } {
  const t = item.track as unknown;
  return !!t && typeof t === "object" && (t as any).type === "track" && "duration_ms" in (t as any);
} 