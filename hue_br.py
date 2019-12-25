from hue import HueBackup
import argparse

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Hue Bridge Backup and Recovery")
    parser.add_argument("bridge", help="name or IP address of the Hue bridge to backup or recover")
    parser.add_argument("key", help="API key of the bridge under which to backup or recover")
    parser.add_argument_group()
    parser.add_argument("-b", "--backup", metavar="FILENAME", help="run backup of the bridge")
    parser.add_argument("-r", "--restore", metavar="FILENAME", help="run recovery of the bridge")
    args = parser.parse_args()

    br = HueBackup(args.bridge, args.key)
    if args.backup:
        br.backup(args.backup)
    if args.restore:
        br.restore(args.restore)
    if not args.backup and not args.restore:
        raise Exception("At least one of --backup and --restore has to be specified") 