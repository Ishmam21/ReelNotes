"""Generate and save a guide for an existing playlist using the normal API functions."""
import argparse
from pathlib import Path
from uuid import UUID
from sqlalchemy import select
from app.db import get_engine, playlists, videos, playlist_items
from app.main import generate, download_guide


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--playlist-id', type=UUID)
    parser.add_argument('--shortcode', default='DbO58xwPayj')
    parser.add_argument('--output', type=Path, default=Path('../examples/real-playlist/AGENTS.md'))
    args = parser.parse_args()
    playlist_id = args.playlist_id
    if playlist_id is None:
        with get_engine().connect() as conn:
            matches = conn.execute(select(playlists.c.id).join(playlist_items, playlists.c.id == playlist_items.c.playlist_id)
                .join(videos, videos.c.id == playlist_items.c.video_id).where(videos.c.shortcode == args.shortcode)).scalars().all()
        if len(matches) != 1:
            raise SystemExit('Specify --playlist-id: expected exactly one playlist containing this Reel.')
        playlist_id = matches[0]
    guide = generate(playlist_id)
    markdown = download_guide(guide['id']).body.decode('utf-8')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding='utf-8')
    print(markdown)
    print(f'Saved {args.output}; original evidence is stored with guide {guide["id"]}.')


if __name__ == '__main__':
    main()
