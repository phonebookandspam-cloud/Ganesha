"""Normalize an sdist tar.gz for deterministic source-package hashes."""
import argparse
import gzip
import io
import os
import pathlib
import tarfile
import tempfile


def normalize_sdist(archive_path, source_date_epoch):
    archive_path = pathlib.Path(archive_path)
    if type(source_date_epoch) is not int or source_date_epoch < 0:
        raise ValueError("SOURCE_DATE_EPOCH must be a non-negative integer")

    fd, temporary_name = tempfile.mkstemp(prefix=archive_path.name + ".", suffix=".tmp", dir=str(archive_path.parent))
    os.close(fd)
    temporary_path = pathlib.Path(temporary_name)
    try:
        with tarfile.open(str(archive_path), mode="r:gz") as source:
            members = sorted(source.getmembers(), key=lambda item: item.name)
            with open(temporary_path, "wb") as raw_output:
                with gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0, compresslevel=9) as compressed:
                    with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as target:
                        for member in members:
                            path = pathlib.PurePosixPath(member.name)
                            if path.is_absolute() or ".." in path.parts or "\\" in member.name:
                                raise ValueError("Unsafe path in source archive: %s" % member.name)
                            if not (member.isdir() or member.isfile()):
                                raise ValueError("Unsupported archive member type: %s" % member.name)
                            normalized = tarfile.TarInfo(member.name)
                            normalized.type = member.type
                            normalized.mode = member.mode
                            normalized.uid = 0
                            normalized.gid = 0
                            normalized.uname = ""
                            normalized.gname = ""
                            normalized.mtime = source_date_epoch
                            normalized.pax_headers = {}
                            if member.isdir():
                                normalized.size = 0
                                target.addfile(normalized)
                            else:
                                content = source.extractfile(member)
                                if content is None:
                                    raise ValueError("Unable to read archive member: %s" % member.name)
                                data = content.read()
                                normalized.size = len(data)
                                target.addfile(normalized, io.BytesIO(data))
        os.replace(temporary_path, archive_path)
    except Exception:
        try:
            temporary_path.unlink()
        except FileNotFoundError:
            pass
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="+")
    args = parser.parse_args()
    raw_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if raw_epoch is None or not raw_epoch.isdigit():
        parser.error("SOURCE_DATE_EPOCH must be set to a non-negative Unix timestamp")
    epoch = int(raw_epoch)
    for archive in args.archives:
        normalize_sdist(archive, epoch)
        print("normalized %s" % archive)


if __name__ == "__main__":
    main()
