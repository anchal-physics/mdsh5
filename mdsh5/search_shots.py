import argparse
import shutil
import os
import yaml
from .read_mds import search_shots


def get_args():
    parser = argparse.ArgumentParser(description='Search MDSPlus server for '
                                                 'provided search criteria and return '
                                                 'a list of shots')
    parser.add_argument('-c', '--search_config', default=None, type=str,
                        help='Configuration file containing search criteria. ')
    parser.add_argument('-s', '--server', default=None,
                        help='Server address. Default is None (read from search_config).')
    parser.add_argument('-o', '--out_filename', default=None,
                        help='Output filename for saving selected shot numbers. '
                             'Default is None in which case it looks for the value in '
                             'search_config otherwise the selected shots are simply '
                             'printed out.')
    parser.add_argument('--configTemplate', action='store_true',
                        help='If provided, configuration templates will be copied to '
                             'current directory. All other arguments will be ignored.')
    args = parser.parse_args()
    return args

def search_shots_cli():
    """
    Command line version of read_mds which gets converted into a script in package.
    """
    args = get_args()
    if args.configTemplate:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.join(root_dir, 'config_examples')
        dest = os.getcwd()
        shutil.copy(os.path.join(src_dir, 'search_d3d.yml'), dest)
        shutil.copy(os.path.join(src_dir, 'search_kstar.yml'), dest)
        return 0
    with open(args.search_config, 'r') as f:
        search_config = yaml.safe_load(f)
    shot_list = search_shots(search_config=search_config, server=args.server)
    if args.out_filename is None and 'out_filename' not in search_config:
        for shot in shot_list:
            print(shot)

if __name__ == '__main__':
    search_shots_cli()
