"""Shared, Qt-free access to existing Bambu 3MF thumbnail resources."""
PREVIEW_MEMBERS = ('Metadata/plate_1.png', 'Metadata/thumbnail.png', 'Metadata/plate_1_small.png')

def read_3mf_preview(archive):
    for name in PREVIEW_MEMBERS:
        try:
            info = archive.getinfo(name)
        except KeyError:
            continue
        if info.file_size <= 5*1024*1024:
            return archive.read(info)
    return None
