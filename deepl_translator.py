import deepl
import dotenv
import json
import re

from argparse import ArgumentParser
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import Optional, Any


class Translator:
    def __init__(self):
        self.resources_path: Optional[Path] = None
        self.json_path: Optional[Path] = None
        self.source_path: Optional[Path] = None
        self.translated_source_path: Optional[Path] = None
        self.raw_path: Optional[Path] = None
        self.start_date: Optional[datetime] = None
        self.deepl: Any = deepl.Translator(self.auth_key)
        self.max_chars_per_month = 0
        self.sent_chars = 0
        self.source = ''
        self.source_items = set()
        self.target_items = []
        self.search_pattern = re.compile(
            r'(?P<both><source>(?P<source>[^<]+)</source>\s+(?P<target><target state="needs-translation"/>))',
            re.S
        )
        self.done_pattern = re.compile(
            r'<source>(?P<source>.+)</source>\s+?<target>(?P<target>.+)</target>',
            re.UNICODE
        )
        self._set_paths()

    @property
    def auth_key(self):
        auth_key = args.deepl_authkey if args.deepl_authkey else dotenv.get_key('resources/.env', 'DEEPLAUTHKEY')
        if not auth_key:
            raise KeyError('Debe proporcionar una clave API de deepl.')
        return auth_key

    def _set_paths(self):
        self.resources_path = Path('./resources')
        self.json_path = self.resources_path.joinpath('deepl.json')
        if args.source:
            self.source_path = self.resources_path.joinpath(f'{args.source}.xlf')
            self.translated_source_path = self.resources_path.joinpath(f'{args.source}.translated.xlf')
        else:
            raise NameError('Se debe proporcionar un fichero fuente con la opción -f')
        self.raw_path = self.resources_path.joinpath(f'translations_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt')

    def load(self):
        with self.json_path.open('r', encoding='utf8') as fp:
            data = json.load(fp)
        self.max_chars_per_month = data['max_chars_per_month']
        self.sent_chars = data['sent_chars']
        self.start_date = datetime.strptime(data['date'], '%Y-%m-%d %H:%M')
        next_date = self.start_date + relativedelta(months=1)
        if datetime.now() > next_date:
            self.start_date = datetime.now()

    def save(self):
        with self.json_path.open('w', encoding='utf8') as fp:
            data = {
                'max_chars_per_month': self.max_chars_per_month,
                'sent_chars': self.sent_chars,
                'date': f"{self.start_date:%Y-%m-%d %H:%M}"
            }
            json.dump(data, fp)

    def read_source(self):
        with self.source_path.open('r', encoding='utf8') as f:
            self.source = f.read()

    def read_and_show(self):
        self.read_source()
        self.get_untranslated_items()
        items = '\n'.join(self.source_items)
        print(items)
        print(f'items: {len(self.source_items)} size: {len(items)}')

    def get_untranslated_items(self):
        sources = set()
        skip = ('Cantidad', 'Descripción', 'Unidad de medida', 'Total', 'Subtotal')
        for items in self.search_pattern.finditer(self.source):
            expr, source, target = items.groups()
            sources.add(source)
        sources = sources.difference(skip)
        old_sources = len(sources)
        known_translations = self.collect_translations()
        sources.difference_update(known_translations.keys())
        if len(sources) == 0 and old_sources > 0:
            raise IndexError('Ya se han traducido todas las expresiones.')
        self.source_items = list(sorted(sources))

    def save_raw(self):
        translations = '\n'.join(f'{k}: {v}' for k, v in zip(self.source_items, self.target_items))
        with self.raw_path.open('w', encoding='utf8') as fp:
            fp.write(translations)

    def translate(self):
        translations = {k: v for k, v in zip(self.source_items, self.target_items)}
        target_text = f'{self.source}'
        new_line = '\n'
        for k, v in translations.items():
            old = f'<source>{k}</source>{new_line:<11}<target state="needs-translation"/>'
            new = f'<source>{k}</source>{new_line:<11}<target>{v}</target>'
            target_text = target_text.replace(old, new)

        with self.translated_source_path.open('w', encoding='utf8') as fp:
            fp.write(target_text)

    def collect_translations(self):
        if not self.translated_source_path.exists():
            raise FileNotFoundError('No se encontró el fichero fuente.')
        with self.translated_source_path.open('r', encoding='utf8') as fp:
            text = fp.read()
        translations_list = self.done_pattern.findall(text)
        translations_list.sort(key=lambda it: it[0])
        translations = {k: v for k, v in dict(translations_list).items()}
        return translations

    def test(self):
        self.load()
        self.read_source()
        self.get_untranslated_items()
        print(self.source_items)

    def main(self):
        self.load()
        self.read_source()
        self.get_untranslated_items()
        self.collect_translations()
        source = '\n'.join(self.source_items)
        length = len(source)
        if self.max_chars_per_month <= self.sent_chars + length:
            raise OverflowError('Se ha superado el número de carácteres mensuales permitidos por el API.')
        if source:
            source_lang = args.source_lang if args.source_lan else 'en'
            target_lang = args.source_lang if args.source_lan else 'es'
            result = self.deepl.translate_text(source, source_lang=source_lang, target_lang=target_lang)
            translations = result.text
            self.sent_chars += length
            self.save()
            self.target_items = translations.split('\n')
            self.save_raw()
            self.translate()
        else:
            raise NameError('El fichero fuente está vacío.')


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('-c', '--collect', dest='collect', action="store_true")
    parser.add_argument('-f', '--filename', '--source', dest='source')
    parser.add_argument('-k', '--deepl', '--authkey', dest='deepl_authkey')
    parser.add_argument('-r', '--read', dest='read', action="store_true")
    parser.add_argument('-s', '--sourcelang', dest='source_lang')
    parser.add_argument('-t', '--targetlang', dest='target_lang')
    parser.add_argument('-T', '--translate', dest='translate')
    parser.add_argument('-x', '--test', dest='test', action="store_true")
    args = parser.parse_args()

    translator = Translator()
    if args.read:
        translator.read_and_show()
    elif args.collect:
        translator.collect_translations()
    elif args.test:
        translator.test()
    elif args.translate:
        translator.main()
