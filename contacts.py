"""Read-only adapter for KDE Connect's vCard cache. No contact database."""
import base64
import os
from pathlib import Path
import quopri
import re


def unescape(value):
    return re.sub(r'\\([nN,;\\])', lambda m: '\n' if m[1].lower() == 'n' else m[1], value)


def parse_vcard(raw, contact_id=''):
    # Preserve source bytes until each property's charset/encoding is known.
    lines = raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n').split(b'\n')
    unfolded = []
    for line in lines:
        if unfolded and b'ENCODING=QUOTED-PRINTABLE' in unfolded[-1].split(b':', 1)[0].upper() and unfolded[-1].endswith(b'='):
            unfolded[-1] = unfolded[-1][:-1] + line.lstrip(b' \t')
        elif line.startswith((b' ', b'\t')) and unfolded:
            unfolded[-1] += line[1:]
        else:
            unfolded.append(line)
    name = ''; fallback = ''; numbers = []
    for line in unfolded:
        header, sep, value = line.partition(b':')
        if not sep: continue
        parts = header.decode('ascii', errors='ignore').split(';')
        prop = parts[0].split('.')[-1].upper()
        if prop not in ('FN', 'N', 'TEL'): continue
        params = {}; labels = []
        for item in parts[1:]:
            key, eq, val = item.partition('=')
            if eq: params[key.upper()] = val.strip('"')
            else: labels.append(key)
        try:
            encoding = params.get('ENCODING', '').upper()
            if encoding == 'QUOTED-PRINTABLE': value = quopri.decodestring(value)
            elif encoding in ('B', 'BASE64'): value = base64.b64decode(value)
            text = value.decode(params.get('CHARSET', 'utf-8'), errors='replace')
        except (LookupError, ValueError):
            continue
        text = unescape(text).strip()[:1024]
        if prop == 'FN': name = text
        elif prop == 'N': fallback = ' '.join(x for x in text.split(';')[1:3] + text.split(';')[:1] if x)
        elif prop == 'TEL':
            if text.lower().startswith('tel:'): text = text[4:]
            if text and len(numbers)<32 and text not in [n['number'] for n in numbers]:
                label = ', '.join(params.get('TYPE', ','.join(labels)).split(',')).title() or 'Phone'
                numbers.append({'number': text, 'label': label})
    return {'id': contact_id, 'name': name or fallback or (numbers[0]['number'] if numbers else ''), 'numbers': numbers}


def read_contacts(device, data_home=None):
    if not re.fullmatch(r'[A-Za-z0-9_]+', device): raise ValueError('Invalid device identifier')
    data = Path(data_home or os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share')))
    directory = data / 'kpeoplevcard' / ('kdeconnect-' + device)
    contacts = []; skipped = 0; consumed = 0
    for index, file in enumerate(directory.glob('*.vcf')):
        if index>=5000 or consumed>=16*1024*1024: skipped+=1;break
        try:
            limit=min(8*1024*1024,16*1024*1024-consumed)
            if file.stat().st_size>limit: skipped+=1;continue
            with file.open('rb') as stream: raw=stream.read(limit+1)
            if len(raw)>limit: skipped+=1;continue
            consumed+=len(raw)
            c = parse_vcard(raw, file.stem)
            if c['numbers']: contacts.append(c)
        except OSError:
            skipped += 1
    contacts.sort(key=lambda c: c['name'].casefold())
    return {'contacts': contacts, 'available': bool(contacts), 'skipped': skipped}
