"""Explicit model preparation; never runs inference or changes the ASR default."""
import argparse
from app import db, model_manager, sensevoice


def main():
    parser = argparse.ArgumentParser(description='Explicit download of selected ASR models; may use several GB.')
    parser.add_argument('--models', nargs='+', choices=model_manager.MODELS, default=['medium', 'large-v3', 'turbo'])
    parser.add_argument('--sensevoice', action='store_true', help='Also download SenseVoice (install runtime separately).')
    args = parser.parse_args()
    db.init()
    for name in args.models:
        if not model_manager.cached(name):
            print('Downloading ' + name, flush=True)
            with db.connection() as con:
                con.execute("INSERT INTO model_installations(model,state) VALUES(?,'downloading') ON CONFLICT(model) DO UPDATE SET state='downloading',error=NULL", (name,))
            model_manager.download(name)
        if not model_manager.cached(name):
            raise RuntimeError(name + ' is not complete. Check network and disk; retry uses cached files.')
        print(name + ': cached', flush=True)
    if args.sensevoice:
        if not model_manager.cached('SenseVoiceSmall'):
            sensevoice.download_snapshot('3847d57b6bdf2dd8875cb1508d2af43d80a16bf7')
        print('SenseVoiceSmall: cached', flush=True)


if __name__ == '__main__':
    main()
