# Spotizerr-Phoenix

<div align="center">

<table>
  <thead>
    <tr>
      <th>Resource</th>
      <th>Link</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>readthedocs</td>
      <td>https://spotizerr-phoenix.readthedocs.io</td>
    </tr>
    <tr>
      <td>Docker Hub</td>
      <td>https://hub.docker.com/u/spotizerrphoenix</td>
    </tr>
    <tr>
      <td>Releases</td>
      <td>https://lavaforge.org/spotizerrphoenix/spotizerr-phoenix/releases</td>
    </tr>
  </tbody>
</table>

</div>

For context, this project is a fork/reincarnation of the original spotizerr repositories to get it back up and running with minimal/required changes

- [Origins for this project](https://lavaforge.org/spotizerr/spotizerr/issues/19):
  - We are not a part of the original dev team of spotizerr and do not have access to previous spotizerr repos and docs
  - For now, minor things have been updated such as the image used in the `docker-compose.yml`, etc
  - The intention is to maintain it to keep it working throughout time
- The original docs are still relevant but must be tailored to the new spotizerr-phoenix images/builds/repos/etc.
  - please refer to the "Legacy Spotizerr" section below for the original README contents
- The plan is to keep the original/legacy docs, stylings, etc as much as possible to pay respects to the original team and will require some refactoring without introducing breaking changes
- There are plans to change a few things so relevant updates will be included as things progress
- Any new changes/features will be documented below (before the legacy section):

## ⚙️ Spotify Device Info Backfill

- On startup the API backfills `data/creds/<account>/device.json` for any Spotify account missing device metadata, filling in defaults for the device name, SHA1-based id, locale, Spotify software version, and system info so subsequent librespot sessions can present the same identity.
- To opt out, set `SPOTIFY_DEVICE_INFO_BACKFILL=false` (or another falsy value such as `0`, `no`, or `off`) in your `.env` or container environment. Existing files are left untouched and requests without stored metadata simply fall back to librespot’s default identity.
- Turning it off keeps any current `device.json` files where they are (nothing is deleted), and if a Spotify account lacks a `device.json` the downstream `deezspot-spotizerr-phoenix` clients just use librespot’s built-in identity defaults instead of applying a captured override.

## 🎙️ Episode Download Support

- This fork officially owns `GET /api/episode/download/{episode_id}`.
- Episode task payloads now surface `final_path` and `terminal_reason` so downstream clients can copy the exact downloaded file and fail with the real terminal reason.
- Episode download automation assumes your host maps `./downloads` to `/app/downloads` in the container.
- The retry loop for repeated identical episode errors is circuit-broken in Phoenix so tasks fail terminally instead of spinning forever.

<details>
  <summary>
    <span style="font-size:2em; font-weight:700;">Legacy Spotizerr</span>
  </summary>

# SUPPORT YOUR ARTISTS

As of 2025, Spotify pays an average of $0.005 per stream to the artist. That means that if you give the equivalent of $5 directly to them (like merch, buying CDs, or just donating), you can """ethically""" listen to them a total of 1000 times. Of course, nobody thinks Spotify payment is fair, so preferably you should give more, but $5 is the bare minimum. Big names probably don't need those $5 dollars, but it might be _the_ difference between going out of business or not for that indie rock band you like.

# Spotizerr

A self-hosted music download manager with a lossless twist. Download everything from Spotify, and if it happens to also be on Deezer, download from there so you get those tasty FLACs.

## Why?

If you self-host a music server with other users than yourself, you almost certainly have realized that the process of adding requested items to the library is not without its friction. No matter how automated your flow is, unless your users are tech-savvy enough to do it themselves, chances are the process always needs some type of manual intervention from you, be it to rip the CDs yourself, tag some random files from youtube, etc. No more! Spotizerr allows for your users to access a nice little frontend where they can add whatever they want to the library without bothering you. What's that? You want some screenshots? Sure, why not:

<details>
  <summary>Main page</summary>
  <img width="393" height="743" alt="image" src="https://github.com/user-attachments/assets/f60e6c51-2ab2-4c4f-8572-a4c43e781758" />
</details>
<details>
  <summary>Search results</summary>
  <img width="385" height="740" alt="image" src="https://github.com/user-attachments/assets/0208e063-092e-4538-b092-5b1ede57fc58" />
</details>
<details>
  <summary>Track view</summary>
  <img width="1632" height="946" alt="image" src="https://github.com/user-attachments/assets/7a2f8240-a3ab-4b71-a772-f983d6bfd691" />
</details>
<details>
  <summary>Download history</summary>
  <img width="1588" height="994" alt="image" src="https://github.com/user-attachments/assets/e34d7dbb-29e3-4d75-bcbd-0cee03fa57dc" />
</details>

## How do I start?

Docs are available at: https://spotizerr.rtfd.io (LEGACY DOCS - See new link at top)

### Common Issues

**Downloads not starting?**

- Check that service accounts are configured correctly
- Verify API credentials are valid
- Ensure sufficient storage space
- "No accounts available" error: Add credentials in settings

**Download failures?**

- Check credential validity and account status
- Audiokey related errors: Spotify rate limit, wait ~30 seconds and retry
- API errors: Ensure Spotify Client ID and Secret are correct

**Watch system not working?**

- Enable the watch system in settings
- Check watch intervals aren't too frequent
- Verify items are properly added to watchlist

**Authentication problems?**

- Check JWT secret is set
- Verify SSO credentials if using
- Clear browser cache and cookies

**Queue stalling?**

- Verify service connectivity
- Check for network issues

### Logs

Access logs via Docker:

```bash
docker logs spotizerr
```

**Log and File Locations:**

- Application Logs: `docker logs spotizerr` (main app and Celery workers)
- Individual Task Logs: `./logs/tasks/` (inside container, maps to your volume)
- Credentials: `./data/creds/`
- Configuration Files: `./data/config/`
- Downloaded Music: `./downloads/`
- Watch Feature Database: `./data/watch/`
- Download History Database: `./data/history/`
- Spotify Token Cache: `./.cache/` (if `SPOTIPY_CACHE_PATH` is mapped)

**Global Logging Level:**
The application's global logging level can be controlled via the `LOG_LEVEL` environment variable.
Supported values (case-insensitive): `CRITICAL`, `ERROR`, `WARNING`, `INFO`, `DEBUG`, `NOTSET`.
If not set, the default logging level is `WARNING`.
Example in `.env` file: `LOG_LEVEL=DEBUG`

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

Here is the text to add to your `README.md` file, preferably after the "Quick Start" section:

## 💻 Development Setup

To run Spotizerr in development mode:

1.  **Backend (API):**
    - Ensure Python dependencies are installed (e.g., using `uv pip install -r requirements.txt`).
    - Start a Redis server.
    - Run the app insidie your activated virtual env: `python3 app.py`
2.  **Frontend (UI):**
    - Navigate to `spotizerr-ui/`.
    - Install dependencies: `pnpm install`.
    - Start the development server: `pnpm dev`.

## 📄 License

This project is licensed under the GPL yada yada, see [LICENSE](LICENSE) file for details.

## ⚠️ Important Notes

- **Credentials stored in plaintext** - Secure your installation appropriately
- **Service limitations apply** - Account tier restrictions and geographic limitations

### Legal Disclaimer

This software is for educational purposes and personal use only. Ensure you comply with the terms of service of Spotify, Deezer, and any other services you use. Respect copyright laws and only download content you have the right to access.

### File Handling

- Downloaded files retain original metadata
- Service limitations apply based on account types

### Contributing

See [CONTRIBUTING.md](./CONTRIBUTING.md)

## 🙏 Acknowledgements

This project was inspired by the amazing [deezspot library](https://github.com/jakiepari/deezspot). Although their creators are in no way related to Spotizerr-Phoenix, they still deserve credit for their excellent work.

</details>
