import deepl
import dotenv
import json
import re

from argparse import ArgumentParser
from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import Any, Dict, List, Optional


class DeeplHistory:
    def __init__(self):
        self.old_data: Optional[List[Dict[str, Any]]] = None
        self.resources_path = Path('./resources')
        self.json_path: Optional[Path] = None
        self.max_chars_per_month = 0
        self.sent_chars = 0
        self.start_date: Optional[datetime] = None
        self.last_date: Optional[datetime] = None

    def init(self):
        self.json_path = self.resources_path.joinpath('deepl.json')
        with self.json_path.open('r', encoding='utf8') as fp:
            self.old_data = json.load(fp)
        data = self.old_data[-1]
        self.max_chars_per_month = data['max_chars_per_month']
        self.sent_chars = data['sent_chars']

        self.start_date = datetime.strptime(data['date'], '%Y-%m-%d %H:%M')
        next_date = self.start_date + relativedelta(months=1)
        if datetime.now() > next_date:
            self.start_date = datetime.now()
            self.sent_chars = 0

    def save(self):
        with self.json_path.open('w', encoding='utf8') as fp:
            new_data = {
                'max_chars_per_month': self.max_chars_per_month,
                'sent_chars': self.sent_chars,
                'date': f"{self.start_date:%Y-%m-%d %H:%M}",
                'last':  f"{datetime.now():%Y-%m-%d %H:%M}"
            }
            self.old_data.append(new_data)
            json.dump(self.old_data, fp, indent=2)


class DeeplTranslator:
    def __init__(self):
        self.resources_path: Optional[Path] = None
        self.history = DeeplHistory()
        self.source_path: Optional[Path] = None
        self.translated_source_path: Optional[Path] = None
        self.raw_path: Optional[Path] = None
        self.start_date: Optional[datetime] = None
        self.deepl: Any = deepl.Translator(self.auth_key)
        self.source = ''
        self.source_in_env = False
        self.source_items = set()
        self.target_items = []
        self.keep_known_translations: bool = False
        self.fixes = {}
        self.search_pattern = re.compile(
            r'(?P<both><source>(?P<source>[^<]+)</source>\s+(?P<target><target state="needs-translation"/>))',
            re.S
        )
        self.comment_pattern = re.compile(
            r'(?P<both><source>(?P<source>[^<]+)</source>\s+(?P<target><target state="needs-translation"/>))\s+'
            r'(?P<comment><note from="Developer" annotates="general" priority="2">(?P<code>[a-z]{2}-[A-Z]{2})='
            r'"(?P<expression>[^"]+)"</note>)',
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

        if args.source_in_env:
            args.source = dotenv.get_key('resources/.env', 'SOURCE')

        if args.source:
            self.source_path = self.resources_path.joinpath(f'{args.source}.xlf')
            self.translated_source_path = self.resources_path.joinpath(f'{args.source}.translated.xlf')
        else:
            raise NameError('Se debe proporcionar un fichero fuente con la opción -f')
        self.raw_path = self.resources_path.joinpath(f'translations_{datetime.now():%Y-%m-%d_%H-%M-%S}.txt')

    def load(self):
        self.history.init()

    def read_source(self):
        with self.source_path.open('r', encoding='utf8') as f:
            self.source = f.read()

    def read_and_show(self):
        self.read_source()
        self.get_untranslated_items()
        items = '\n'.join(self.source_items)
        print(items)
        print(f'items: {len(self.source_items)} size: {len(items)}')

    def skip_expressions(self):
        expressions = []
        with open('resources/skip_expressions.txt') as fp:
            text = fp.read()
        for expression in text.splitlines():
            expressions.append(expression.strip())
        return expressions

    def get_fixes(self):
        with open('resources/fixes.json') as fp:
            fixes = json.load(fp)
        return fixes

    def fix(self):
        translations = self.collect_translations()
        fixes = self.get_fixes()
        data = {}
        tr = translations.copy()
        for src_lang, tgt_lang in tr.items():
            for fix in fixes:
                if fix in tgt_lang:
                    data.update({tgt_lang: tgt_lang.replace(fix, fixes[fix])})

        with self.translated_source_path.open('r+', encoding='utf8') as fp:
            old_text = fp.read()
            new_text = str(old_text)
            for typo, fix in data.items():
                new_text = new_text.replace(typo, fix)
            if old_text == new_text:
                raise NotImplementedError('Ací passa algo estrany!')
            fp.seek(0)
            fp.write(new_text)
            fp.truncate()

    def get_untranslated_items(self):
        sources = set()
        skip = self.skip_expressions()
        for items in self.search_pattern.finditer(self.source):
            expr, source, target = items.groups()
            sources.add(source)
        sources = sources.difference(skip)
        if self.keep_known_translations:
            known_translations = self.collect_translations()
            not_translated_sources = sources.difference(known_translations.keys())
            if len(not_translated_sources) == 0 and len(sources) > 0:
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
            # raise FileNotFoundError('No se encontró el fichero fuente.')
            return {}
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

    def replace_comments(self):
        indent = '          '
        for items in self.comment_pattern.finditer(self.source):
            both, source, target, comment, lang_code, transl = items.groups()
            repl = items.group(0)
            new = f'<source>{source}</source>\n{indent}<target>{transl}</target>\n{indent}{comment}'
            self.source = self.source.replace(repl, new)

    def main(self):
        self.load()
        self.read_source()
        self.get_untranslated_items()
        self.collect_translations()
        source = '\n'.join(self.source_items)
        length = len(source)
        if self.history.max_chars_per_month <= self.history.sent_chars + length:
            raise OverflowError('Se ha superado el número de carácteres mensuales permitidos por el API.')
        if source:
            source_lang = args.source_lang if args.source_lang else 'en'
            target_lang = args.source_lang if args.source_lang else 'es'
            result = self.deepl.translate_text(source, source_lang=source_lang, target_lang=target_lang)
            translations = result.text
            self.history.sent_chars += length
            self.history.save()
            self.target_items = translations.split('\n')
            self.save_raw()
            self.translate()
        else:
            raise NameError('El fichero fuente está vacío.')

    def use_comments(self):
        self.load()
        self.read_source()
        self.replace_comments()
        try:
            self.get_untranslated_items()
        except IndexError as exception:
            pass
        with self.translated_source_path.open('w', encoding='utf8') as fp:
            fp.write(self.source)


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('-c', '--collect', dest='collect', action="store_true")
    parser.add_argument('-f', '--filename', '--source', dest='source')
    parser.add_argument('-F', '--envfilename', '--envsource', dest='source_in_env', action="store_true")
    parser.add_argument('-k', '--deepl', '--authkey', dest='deepl_authkey')
    parser.add_argument('-K', '--keep', action="store_true", dest='keep_known_translations')
    parser.add_argument('-r', '--read', dest='read', action="store_true")
    parser.add_argument('-s', '--sourcelang', dest='source_lang')
    parser.add_argument('-t', '--targetlang', dest='target_lang')
    parser.add_argument('-T', '--translate', dest='translate', action="store_true")
    parser.add_argument('-u', '--usecomments', dest='use_comments', action="store_true")
    parser.add_argument('-x', '--test', dest='test', action="store_true")
    parser.add_argument('-X', '--fixes', dest='fix', action="store_true")
    args = parser.parse_args()

    translator = DeeplTranslator()
    translator.keep_known_translations = args.keep_known_translations
    translator.source_in_env = args.source_in_env
    if args.read:
        translator.read_and_show()
    elif args.fix:
        translator.fix()
    elif args.collect:
        translator.collect_translations()
    elif args.test:
        translator.test()
    elif args.use_comments:
        translator.use_comments()
    elif args.translate:
        translator.main()

    """
    ### Configuración ###
    
    El fichero de configuración resources/.env contiene el token para el API. (Clave: DEEPLAUTHKEY=) 
    Se puede indicar el fichero fuente a traducir en el fichero de configuración con la clave SOURCE=. En la orden se
    añade --envsource.
    
    También se puede añadir el fichero fuente en la línea de órdenes cin --filename "fichero-de-traducciones.xlf"
    
    ### Pasos ###
    
    1.- Nos traemos a la subcarpeta resources/ el fichero de texto fuente a traducir.
    
    2.- Ejecutamos --read,
        Si hay expresiones que no queremos mandar a traducir a Deepl las introducimos en skip_expressions.txt
        una por línea. (Por ejemplo, expresiones que ya están en castellano.)
        
    3.- Ejecutamos --translate. Esta orden le manda al API de Deepl las expresiones que tenemos que traducir, hay que
    tener en cuenta que son 500.000 carácteres al mes, el recuento se hace en deepl.json.
    
    4.- Leemos de nuevo, si alguna expresión está mal, añadimos en fixes.json la expr. incorrecta y la corrección que
    queremos que se haga a modo de clave valor. Una vez las hemos obtenido, ejecutamos --fixes.
        A modo de ejemplo, los «DISC.» no los traducía y los pasé a «DTO.».
    
    """
