"""Offline, deterministic input-contract example. Does not call a model or create Runs.

This parser deliberately accepts only the pinned Completed SampleData source.
It is not an agent integration or a general C# interpreter.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

SOURCE_SHA256 = 'cab15100c9230e325ae513c7a9d8b09dc90f21cd7b489a54b0fa93cc2e7512ed'
SOURCE_PATH = '/inputs/legacy-source/MvcMusicStore-Completed/MvcMusicStore/Models/SampleData.cs'
DERIVED_PATH = '/inputs/catalog-derived/catalog.json'
TOOL_PATH = '/inputs/catalog-tools/catalog_return_contract.py'
BYTE_CAP = 51200


def digest(value):
    return hashlib.sha256(value).hexdigest()


def encode(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def source_bytes(path):
    data = Path(path).read_bytes()
    if digest(data) != SOURCE_SHA256:
        raise ValueError('Expected pinned Completed source; do not substitute the Assets catalog')
    return data


def extract(data):
    text = data.decode('utf-8-sig')
    string = r'"(?:[^"\\]|\\.)*"'
    def names(kind):
        return [json.loads(s) for s in re.findall(r'new ' + kind + r' \{ Name = (' + string + r') \}', text)]
    genres, artists = names('Genre'), names('Artist')
    pattern = (r'new Album \{ Title = (' + string + r'), Genre = genres.Single\(g => g.Name == (' + string
               + r')\), Price = (\d+\.\d{2})M, Artist = artists.Single\(a => a.Name == (' + string
               + r')\), AlbumArtUrl = (' + string + r') \}')
    matches = re.findall(pattern, text)
    if len(genres) != 10 or len(matches) != 246 or len(matches) != text.count('new Album {'):
        raise ValueError('Incomplete extraction')
    if len(set(genres)) != len(genres) or len(set(artists)) != len(artists):
        raise ValueError('Ambiguous name lookup')
    albums = []
    for number, (title, genre, price, artist, art) in enumerate(matches, 1):
        title, genre, artist, art = map(json.loads, (title, genre, artist, art))
        albums.append({'albumId': number, 'title': title, 'genreId': genres.index(genre) + 1,
                       'artistId': artists.index(artist) + 1, 'price': price, 'albumArtUrl': art})
    return {'genres': [{'genreId': n, 'name': s} for n, s in enumerate(genres, 1)],
            'artists': [{'artistId': n, 'name': s} for n, s in enumerate(artists, 1)], 'albums': albums}


def excerpt(data, offset, limit):
    lines = data.decode('utf-8-sig').splitlines()
    if not 1 <= offset <= len(lines) or not 1 <= limit <= 360:
        raise ValueError('offset must name a source line; limit must be 1..360')
    selected, size = [], 0
    for line in lines[offset - 1:offset - 1 + limit]:
        raw = (line + '\n').encode('utf-8')
        if size + len(raw) > BYTE_CAP:
            break
        selected.append(line); size += len(raw)
    if not selected:
        raise ValueError('A source line exceeds the byte cap')
    next_offset = offset + len(selected)
    header = {'source_sha256': SOURCE_SHA256, 'offset': offset, 'requested_lines': limit,
              'delivered_lines': len(selected), 'body_utf8_bytes': size, 'body_byte_cap': BYTE_CAP,
              'next_offset': next_offset if next_offset <= len(lines) else None, 'eof': next_offset > len(lines)}
    return ('CATALOG_SOURCE ' + json.dumps(header, sort_keys=True, separators=(',', ':')) + '\n'
            + '\n'.join(selected) + '\n').encode('utf-8')


def prepare(source, out):
    data = source_bytes(source)
    catalog = extract(data)
    encoded = encode(catalog)
    counts = Counter(a['genreId'] for a in catalog['albums'])
    anchors = {str(n): catalog['albums'][n-1]['title'] for n in (1, 2, 246)}
    if anchors != {'1': 'The Best Of Men At Work', '2': 'A Copland Celebration, Vol. I', '246': 'Ao Vivo [IMPORT]'}:
        raise ValueError('Insertion order check failed')
    common = encode({'source': SOURCE_PATH, 'source_sha256': SOURCE_SHA256, 'catalog': DERIVED_PATH,
                     'catalog_sha256': digest(encoded), 'extraction': 'complete; insertion order preserved; no sorting or LLM',
                     'genres': len(catalog['genres']), 'artists': len(catalog['artists']), 'albums': len(catalog['albums']),
                     'genre_counts': {g['name']: counts[g['genreId']] for g in catalog['genres']},
                     'id_checks': anchors,
                     'read_source': f'python3 {TOOL_PATH} read-source --source {SOURCE_PATH} --offset 361 --limit 71'})
    if len(common) > 2048:
        raise ValueError('Common confirmation exceeds 2048 UTF-8 bytes')
    raw = excerpt(data, 1, 360)
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    for name, value in {'catalog.json': encoded, 'common.json': common, 'raw-first.txt': raw,
                        'compact-context.txt': common, 'expanded-context.txt': common + raw}.items():
        (out/name).write_bytes(value)
    manifest = {'model_called': False, 'source_sha256': SOURCE_SHA256,
                'extractor_sha256': digest(Path(__file__).read_bytes()),
                'files': {p.name: {'sha256': digest(p.read_bytes()), 'bytes': p.stat().st_size} for p in out.iterdir()},
                'raw_header': json.loads(raw.splitlines()[0].decode().removeprefix('CATALOG_SOURCE '))}
    (out/'manifest.json').write_bytes(encode(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--source', required=True); prep.add_argument('--out', required=True)
    read = sub.add_parser('read-source'); read.add_argument('--source', required=True)
    read.add_argument('--offset', type=int, required=True); read.add_argument('--limit', type=int, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        print(json.dumps(prepare(args.source, args.out), indent=2))
    else:
        import sys
        sys.stdout.buffer.write(excerpt(source_bytes(args.source), args.offset, args.limit))
