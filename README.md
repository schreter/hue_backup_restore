# Hue Backup/Restore

This project provides backup and (partial) restore functionality for Philips Hue bridge.

## Prerequisites

To run the scripts you need to have a recent Python installed. No special Python packages
are needed, just `requests`, `json`, `argparse` and `re` are used.

To backup and restore the bridge, you need to have an API key. Please refer to Hue
documentation [here](https://developers.meethue.com/develop/get-started-2/#so-lets-get-started).

It is recommended to restart the bridge before the backup to get rid of deleted resources,
so they won't be backed up, however, this is not strictly necessary. Deleted rules will
be ignored and unused recyclable resources will be recycled on the new bridge at the latest
after the next restart.

It is strongly recommended to use unique names for all rooms, groups, group scenes within
a group, schedules, rules, etc., since matching is done by name (except for lights and
sensors/accessories, where the matching is done using unique ID).

The backup functionality does some duplicate name checks to prevent issues with restore
(and repeated restore) on the destination bridge and renames the items by adding numeric
suffix or prefix to make them unique. However, this is not 100% safe (and may change
semantics).


## Backing Up

Backup can be executed using:
```
python hue_br.py -b <filename.json> <bridge IP> <API key>
```

This generates a JSON file with dump of the complete bridge state. This has intentionally
a very simple implementation to prevent possible bugs. This state is then matched at
recovery time with whatever is found on the other bridge.


## Restoring

Restoring is, unfortunately, not straightforward. First, you need to initialize a new bridge
where you what to restore. Then, you need to connect all lights and sensors to this new bridge
manually. Do not give them any names or any configuration just yet, this will be done by the
restore script (i.e., use "configure in a different application" when adding new sensors).
After this is done, execute restore using:
```
python hue_br.py -r <filename.json> <new bridge IP> <new API key>
```

Restore script does the following:
* match lights and sensors found in the backup with those in the bridge
* rename lights and sensors to the names in the backup
* create/update rooms and zones
* recreate any missing or update any existing CLIP sensors, schedules, rules, resource
  links, etc. to match those in the original bridge
* clean up any resource links which do not reference a rule or schedule touching
  a light (e.g., only touching restored CLIP sensors for non-existing accessories/rooms
  after a partial restore)

Additionally, restore also updates wake-up schedules to make them work on the new
bridge. Other routine types created by Hue app were not tested so far.

Restore works best if there is nothing except lights and sensors in the bridge, i.e.,
no rules, schedules, etc. This is normally the case when restoring to a new bridge.
However, it works well also if a restore with the same backup has been done previously.
E.g., if you don't connect all lights/sensors in the first run, the restore will print
a lot of warnings regarding what's missing. You can now add remaining lights/sensors
and re-run the restore. This will restore additional configuration.

If you by mistake configured an accessory before restore, you'll need to manually
remove this configuration (e.g., by deleting the accessory and re-adding it, this time
without configuring it, or for power users via the API). Otherwise, you'll risk having
double actions for the accessory.

The restore may also break because of an error when executing a command on the bridge.
This can happen if you have circular references (e.g., rules enabling/disabling other
rules and the like). You may try recovery again, potentially after manually reorganizing
the items in the backup to fix the dependency order. However, this is not a typical
use case.


## Last Words

Needless to say, this software is provided under GPL without any warranty. Your mileage
may vary. I successfully did a partial restore to split my large Hue installation onto
two bridges.

Refer to [LICENSE](LICENSE) for the full license text.

You may also want to check out my other companion projects:
* [Hue rule configurator](https://github.com/schreter/hue_rule_configurator) to describe
  what you want in JSON and to (re-)generate rules based on it on the bridge (Python)
* [EnOcean to Hue gateway](https://github.com/schreter/enocean_to_hue) to route EnOcean
  packets as external input in the Hue bridge (C++)