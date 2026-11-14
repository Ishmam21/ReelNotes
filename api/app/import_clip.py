"""Explicitly import an owned local clip for a queued Reel; never substitutes automatically."""
import argparse
from pathlib import Path
from uuid import UUID, uuid4
from sqlalchemy import text
from app.db import get_engine
from app.worker import process_job


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('video_id', type=UUID, help='Queued video ID created through the API')
    parser.add_argument('clip', type=Path)
    parser.add_argument('--owned', action='store_true', required=True, help='Confirm permission to process this clip')
    args = parser.parse_args()
    if not args.clip.is_file():
        parser.error('Clip does not exist')
    with get_engine().begin() as connection:
        job = connection.execute(text("""UPDATE reelnotes.videos SET state='downloading',
            attempts=attempts+1, lease_token=:token, lease_until=now()+interval '2 minutes', updated_at=now()
            WHERE id=:id AND state IN ('queued','failed') RETURNING *"""),
            {'id': args.video_id, 'token': uuid4()}).mappings().first()
        if job is None:
            parser.error('Video must exist and be queued or failed; stop the normal worker first')
        job = dict(job)
    process_job(job, args.clip.resolve())


if __name__ == '__main__':
    main()
