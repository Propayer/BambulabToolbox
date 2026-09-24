"""Public HTML/SCAD only. No private API guessing, browser impersonation or login."""
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler
import socket
import ipaddress
import json
import re

NO_SOURCE = 'El código fuente OpenSCAD no está disponible. Sube un 3MF generado por este modelo para intentar reconstruir una versión paramétrica equivalente.'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Redirección rechazada. Introduce la URL pública final.')


def validate_url(url, *, model_page=False):
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443) or not (
        host == 'makerworld.com' or host.endswith('.makerworld.com') or host == 'makerworld.bblmw.com'):
        raise ValueError('Usa una URL HTTPS pública de MakerWorld, sin credenciales.')
    if model_page and not re.match(r'^/(?:[a-z]{2}/)?models/[^/]+', p.path):
        raise ValueError('Introduce la URL de una página /models/ de MakerWorld.')
    return url


def fetch_public(url, limit=2_000_000):
    validate_url(url)
    host = urlsplit(url).hostname
    for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM):
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise ValueError('Dirección de red no pública.')
    req = Request(url, headers={'User-Agent': 'BambuLabToolbox-SCADBuilder/1.0', 'Accept-Encoding': 'identity'})
    with build_opener(NoRedirect()).open(req, timeout=12) as response:
        data = response.read(limit+1)
        if len(data) > limit: raise ValueError('Respuesta demasiado grande.')
        return data.decode('utf-8-sig', errors='replace')


class PublicPage(HTMLParser):
    def __init__(self, url):
        super().__init__(convert_charrefs=True)
        self.url, self.meta, self.links, self.images, self.codes, self.visible = url, {}, [], [], [], []
        self.tag, self.buffer, self.title = '', [], ''
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'meta': self.meta[a.get('property', a.get('name', ''))] = a.get('content', '')
        if tag == 'a' and '.scad' in a.get('href', '').lower(): self.links.append(urljoin(self.url, a['href']))
        if tag == 'img' and a.get('src'): self.images.append(urljoin(self.url, a['src']))
        if tag in ('input', 'select') and a.get('name'):
            self.visible.append({k: a[k] for k in ('name','type','value','min','max','step') if k in a})
        if tag in ('title', 'pre', 'code') or tag == 'script' and a.get('type') == 'application/ld+json':
            self.tag, self.buffer = tag, []
    def handle_data(self, data):
        if self.tag: self.buffer.append(data)
    def handle_endtag(self, tag):
        if tag != self.tag: return
        content = ''.join(self.buffer)
        if tag == 'title': self.title = content
        elif tag in ('pre', 'code') and re.search(r'\b(?:cube|module|linear_extrude|text)\s*[({]', content):
            self.codes.append(content)
        elif tag == 'script':
            try:
                entries = json.loads(content)
                for entry in entries if isinstance(entries, list) else [entries]:
                    if not isinstance(entry, dict): continue
                    for key in ('name', 'description', 'image'): self.meta.setdefault(key, entry.get(key, ''))
            except (ValueError, RecursionError): pass
        self.tag, self.buffer = '', []


def analyze_url(url, *, fetch=fetch_public):
    validate_url(url, model_page=True)
    result = dict(source_url=url, source_platform='MakerWorld', title='', description='', images=[],
                  visible_parameters=[], original_scad_available=False, original_scad=None, warnings=[])
    try:
        page = PublicPage(url); page.feed(fetch(url))
        result.update(title=page.meta.get('og:title') or page.meta.get('name') or page.title,
                      description=page.meta.get('og:description') or page.meta.get('description', ''),
                      images=list(dict.fromkeys([str(page.meta.get('og:image', '')), *page.images]))[:20],
                      visible_parameters=page.visible[:250])
        if page.codes:
            result.update(original_scad_available=True, original_scad=page.codes[0], source_method='public_inline_code')
        else:
            for link in page.links[:5]:
                try:
                    validate_url(link)
                    # Only explicit SCAD file links, never arbitrary URLs or protected APIs.
                    if not urlsplit(link).path.lower().endswith('.scad'): continue
                    code = fetch(link)
                    if '<html' in code.lower(): continue
                    result.update(original_scad_available=True, original_scad=code, source_method='public_scad_link', scad_url=link)
                    break
                except Exception:
                    result['warnings'].append('Un enlace SCAD público no pudo leerse; puedes importar el archivo manualmente.')
    except Exception:
        result['warnings'].append('Página no accesible públicamente desde esta conexión (bloqueo, red o formato). No se ha intentado eludirlo.')
    if not result['original_scad_available']: result['warnings'].append(NO_SOURCE)
    return result
