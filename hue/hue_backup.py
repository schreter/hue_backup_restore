import requests
import json
import re

MATCH_HUEAPP_SCENEDATA = re.compile('^(.....)_r([0-9][0-9])_d([0-9][0-9])$')
MATCH_SCHEDULE_ADDRESS = re.compile('^(/api/[^/]+/)([a-zA-Z0-9_]+)/([a-zA-Z0-9_]+)([^a-zA-Z0-9_].*)?$')
MATCH_RULE_ADDRESS = re.compile('^(/)([a-zA-Z0-9_]+)/([a-zA-Z0-9_]+)([^a-zA-Z0-9_].*)?$')
MATCH_RESOURCE_LINK = re.compile("^/([a-zA-Z0-9_]+)/([a-zA-Z0-9_]+)")

class HueBackup():
    """
    Class for backing up and recovering Hue Bridge settings.
    
    Upon restore, lights  and sensors are expected to be already connected to the new bridge.
    As much as possible will be restored, based on lights and sensors found.

    See README.md for description of the configuration.
    """

    def __init__(self, bridge, apiKey):
        self.bridge = bridge
        self.apiKey = apiKey
        self.urlbase = "http://" + bridge + "/api/" + apiKey;
        self.__updates = []
        self.__errors = []
        self.__refresh()

    def backup(self, filename):
        """
        Store the backup of the bridge into specified file name
        """
        print("Fixing duplicate names")
        self.__fixNames("groups", self.__current["groups"])
        self.__fixNames("rules", self.__current["rules"])
        self.__fixNames("schedules", self.__current["schedules"])
        self.__fixNames("resourcelinks", self.__current["resourcelinks"])
        
        print("Determining light states for scenes")
        for guid, data in self.__current["scenes"].items():
            data = self.__get("scenes/" + guid)
            self.__current["scenes"][guid]["lightstates"] = data["lightstates"]
            
        print("Backing up Hue bridge data to " + filename)
        with open(filename, "w") as f:
            json.dump(self.__current, f, indent=4)

    def __fixNames(self, resource, tree):
        names = {}
        duplicates = {}
        
        # first pass: find duplicate names
        for index, data in tree.items():
            name = data["name"]
            if name in names.keys() and name not in duplicates.keys():
                duplicates[name] = 0
            names[name] = 1
            
        # second pass: fix duplicate names
        for key, data in tree.items():
            name = data["name"]
            if name in duplicates.keys():
                index = duplicates[name]
                if index == 0:
                    duplicates[name] = 1
                    continue
                while True:
                    index = index + 1
                    fixed_name = name + str(index)
                    if len(fixed_name) > 31:
                        # too long name produced, try to do it differently - put index at the beginning
                        fixed_name = str(index) + name
                        fixed_name = fixed_name[0:31]
                    if fixed_name not in names:
                        data["name"] = fixed_name
                        names[fixed_name] = 1
                        print("WARNING: fixing duplicate name '" + name + "' to '" + fixed_name + "' for resource '" + resource + "/" + key + "'")
                        break
                duplicates[name] = index

    def __refresh(self):
        # read all data from the bridge
        self.__current = self.__get("")

    def __get(self, resource):
        tmp = requests.get(self.urlbase + "/" + resource)
        if tmp.status_code != 200:
            raise Exception("Cannot read bridge data: status code " + str(tmp.status_code))
        tmp.encoding = 'utf-8'
        data = json.loads(tmp.text)
        if type(data) is list and "error" in data[0].keys():
            raise Exception("Cannot read bridge data: " + data[0]["error"]["description"])
        return data

    def restore(self, filename):
        """
        Restore the backup from the file into the bridge
        """
        print("Loading Hue bridge data from " + filename)
        with open(filename, "r") as f:
            self.__target = json.load(f)

        self.__map_light = {}
        self.__map_sensor = {"1": "1"}
        self.__map_group = {"0": "0"}
        self.__map_scene = {}
        self.__map_schedule = {}
        self.__map_rule = {}
        self.__map_resource_links = {}

        print("Restoring lights")
        self.__restoreLights()
        self.__run_updates()
        print("Restoring sensors")
        self.__restoreSensors()
        self.__run_updates()
        print("Restoring groups")
        self.__restoreGroups()
        print("Restoring scenes")
        self.__restoreScenes()
        print("Restoring schedules")
        self.__restoreSchedules()
        print("Restoring rules")
        self.__restoreRules()
        print("Restoring resource links")
        self.__restoreResourceLinks()
        print("Cleaning up resources without light control")
        self.__cleanupResourceLinks()
        
        if len(self.__errors) > 0:
            print("ERRORS FOUND:")
            for s in self.__errors:
                print(" - " + s)
        
    def __restoreLights(self):
        """
        Restore light names and build mapping of lights from original bridge to this bridge into __map_light
        """
        s = self.__current["lights"]
        t = self.__target["lights"]
        # first build maps from unique ID to light ID
        sm = self.__make_map(s)
        tm = self.__make_map(t)
        # for each light in target configuration, look up the light in current configuration and reconfigure
        for uniq, index in tm.items():
            if uniq in sm.keys():
                si = sm[uniq]
                sname = s[si]["name"]
                tname = t[index]["name"]
                self.__map_light[index] = si
                print("   - mapping light '" + sname + "' from " + index + " to " + si + " as '" + tname + "'")
                if sname != tname:
                    print("   - renaming light to " + tname)
                    self.__schedule_put(
                        "lights/" + si,
                        {"name": tname}
                    )
            else:
                self.__warning("light " + uniq + " cannot be restored, since it doesn't exist in target bridge")
        print("   - light map: " + str(self.__map_light))

    def __restoreSensors(self):
        """
        Restore sensor names and build mapping of sensors from original bridge to this bridge into __map_sensor
        """
        s = self.__current["sensors"]
        t = self.__target["sensors"]
        # first build maps from unique ID to sensor ID
        sm = self.__make_map(s)
        tm = self.__make_map(t)
        # for each sensor in target configuration, look up the sensor in current configuration and reconfigure
        for uniq, index in tm.items():
            data = t[index]
            # copy known sensor configuration parameters
            # TODO do we have more config values, which can be copied?
            config = {}
            for k in ["on", "sunriseoffset", "sunsetoffset"]:
                if k in data["config"]:
                    config[k] = data["config"][k]
            if uniq in sm.keys():
                si = sm[uniq]
                sname = s[si]["name"]
                tname = data["name"]
                self.__map_sensor[index] = si
                print("   - mapping sendor '" + sname + "' from " + index + " to " + si + " as '" + tname + "'")
                if s[si]["type"] != data["type"]:
                    self.__error("sensor " + uniq + " has different type, expected " + data["type"])
                if sname != tname:
                    print("   - renaming light to " + tname)
                    body = {"name": tname}
                    if len(config.keys()) > 0:
                        body["config"] = config 
                    self.__schedule_put("sensors/" + si, body)
            elif data["type"] == "CLIPGenericFlag" or data["type"] == "CLIPGenericStatus":
                # CLIP sensor can be recreated
                body = {"name" : data["name"], "modelid": data["modelid"], "swversion": data["swversion"], "type": data["type"],
                        "uniqueid": uniq, "manufacturername": data["manufacturername"], "recycle": data["recycle"]}
                print("   - creating sensor " + uniq + ": " + str(body))
                if len(config.keys()) > 0:
                    body["config"] = config 
                self.__map_sensor[index] = self.__post("sensors", body)
            else:
                self.__warning("sensor " + uniq + " cannot be restored, since it doesn't exist in target bridge")
        print("   - sensor map: " + str(self.__map_sensor))

    def __restoreGroups(self):
        """
        Restore groups and build mapping of groups from original bridge to this bridge into __map_group
        """
        s = self.__current["groups"]
        t = self.__target["groups"]
        # build index of groups by name in the source bridge
        nameidx = {}
        for index, data in s.items():
            if data["name"] in nameidx:
                self.__error("duplicate group name " + data["name"])
            nameidx[data["name"]] = index
        tnameidx = {}
        for index, data in t.items():
            name = data["name"]
            if name in tnameidx:
                self.__error("duplicate group name " + name + " at index " + index + " and " + tnameidx[name])
            tnameidx[name] = index
            lights = []
            missing_lights = []
            for lidx in data["lights"]:
                if lidx in self.__map_light:
                    lights.append(self.__map_light[lidx])
                else:
                    missing_lights.append(self.__target["lights"][lidx]["name"])
            sensors = []
            missing_sensors = []
            for sidx in data["sensors"]:
                if sidx in self.__map_sensor:
                    sensors.append(self.__map_sensor[sidx])
                else:
                    missing_sensors.append(self.__target["sensors"][sidx]["name"])
 
            body = {"name" : name, "lights": lights, "sensors": sensors}
            if "class" in data:
                body["class"] = data["class"]
            if len(lights) == 0:
                self.__warning("group " + name + " cannot be restored, since it doesn't contain any lights in the target bridge")
                continue
            
            if len(missing_lights) != 0 or len(missing_sensors) != 0:
                self.__warning("group " + name + " is missing lights " + str(missing_lights) + " or sensors " + str(missing_sensors))

            # find whether the group already exists in this bridge and if it does, update the old one
            idx = None
            if name in nameidx:
                # yes, it exists, update group
                idx = nameidx[name]
                if s[idx]["type"] != data["type"]:
                    self.__error("group " + name + " has different type, expected " + data["type"])
                    continue
                print("   - updating group " + name + '/' + idx)
                self.__put("groups/" + idx, body)
            else:
                # create a new group                
                #body["recycle"] = data["recycle"]
                body["type"] = data["type"]
                print("   - creating group " + name + ": " + str(body))
                idx = self.__post("groups", body)
            self.__map_group[index] = idx
        print("   - group map: " + str(self.__map_group))
    
    def __sceneKey(self, guid, data, mapgroup):
        if data["type"] == "GroupScene":
            g = data["group"]
            if mapgroup:
                # we are generating key for target configuration, but we need group ID from our system
                if g in self.__map_group:
                    g = self.__map_group[g]
                else:
                    # group does not exist in target, use some dummy group ID
                    g = "~" + g
            return g + "%" + data["name"]
        elif data["type"] == "LightScene":
            if "data" in data["appdata"]:
                return data["appdata"]["data"] + "!" + data["name"]
            else:
                return guid + "!" + data["name"]
        else:
            raise Exception("Unknown scene type in " + str(data))
        
    def __restoreScenes(self):
        """
        Restore scenes and fill __map_scene with mapping for existing scenes
        """
        s = self.__current["scenes"]
        t = self.__target["scenes"]
        sm = {}
        tm = {}
        for guid, data in s.items():
            key = self.__sceneKey(guid, data, False)
            if key in sm:
                self.__error("current scene " + guid + " has duplicate key " + key)
            sm[key] = guid
        for guid, data in t.items():
            key = self.__sceneKey(guid, data, True)
            if key in tm:
                self.__error("to-be-restored scene " + guid + " has duplicate key " + key)
            tm[key] = guid
        self.__map_scene = {}
        for key, guid in tm.items():
            data = t[guid]
            
            body = {"name": data["name"]}
            if "group" in data:
                if data["group"] in self.__map_group:
                    body["group"] = self.__map_group[data["group"]]
                else:
                    self.__warning("scene " + guid + " cannot be restored, missing group " + self.__target["groups"][data["group"]]["name"])
                    continue
            elif "lights" in data: 
                lights = []
                missing_lights = []
                for lidx in data["lights"]:
                    if lidx in self.__map_light:
                        lights.append(self.__map_light[lidx])
                    else:
                        missing_lights.append(self.__target["lights"][lidx]["name"])
                if len(lights) == 0:
                    self.__warning("scene " + guid + " cannot be restored, missing all lights " + str(missing_lights))
                    continue
                self.__warning("scene " + guid + " can be only partially restored, missing lights " + str(missing_lights))
                body["lights"] = lights
                
            if not "lightstates" in data:
                self.__error("scene " + guid + " cannot be restored, since light states are not present in backup")
                continue
            
            lightstates = {}
            for lidx, ldata in data["lightstates"].items():
                if lidx in self.__map_light:
                    lightstates[self.__map_light[lidx]] = ldata
            
            if key in sm.keys():
                # scene exists in the bridge, just update it
                old = s[sm[key]]
                if old["type"] != data["type"]:
                    self.__error("scene " + guid + " has different type, expected " + data["type"])
                    continue
                if old["recycle"] != data["recycle"]:
                    self.__error("scene " + guid + " has different recycle flag, expected " + data["recycle"])
                # TODO check lights?
                print("   - updating scene " + guid)
                body["lightstates"] = lightstates
                body.pop("group", None)
                #body.pop("lights", None)
                self.__put("scenes/" + sm[key], body)
                    
            else:
                # new scene, so far does not exist in the bridge
                body["type"] = data["type"]
                body["recycle"] = data["recycle"]
                body["appdata"] = data["appdata"]
                if not "data" in body["appdata"]:
                    # create dummy app data with GUID to have unique scene IDs
                    body["appdata"]["version"] = 1
                    body["appdata"]["data"] = guid
                if data["type"] == "GroupScene":
                    # map appdata to show in Hue App
                    match = MATCH_HUEAPP_SCENEDATA.match(body["appdata"]["data"])
                    if match:
                        g = body["group"]
                        if len(g) == 1:
                            g = "0" + g
                        body["appdata"]["data"] = match.group(1) + "_r" + g + "_d" + match.group(3) 
                if lightstates:
                    body["lightstates"] = lightstates
                print("   - creating scene " + guid)
                sm[key] = self.__post("scenes", body)
                
            self.__map_scene[guid] = sm[key]
        print("   - scene mapping: " + str(self.__map_scene))
        
        
    def __mapAddress(self, address, with_api):
        """
        Map address from old system to the new system, return new address and type or None, None if no mapping possible.
        """
        # update body and address using maps
        match = None
        if with_api:
            match = MATCH_SCHEDULE_ADDRESS.match(address)
        else:
            match = MATCH_RULE_ADDRESS.match(address)
        if not match:
            self.__error("unknown schedule/rule address " + address)
            return None, None
        ctype = match.group(2)
        cid = match.group(3)
        if ctype == "lights":
            if cid in self.__map_light:
                cid = self.__map_light[cid]
            else:
                self.__warning("not importing resource referencing non-existing light " + cid)
                return None, None
        elif ctype == "groups":
            if cid in self.__map_group:
                cid = self.__map_group[cid]
            else:
                self.__warning("not importing resource referencing non-existing group " + cid)
                return None, None
        elif ctype == "sensors":
            if cid in self.__map_sensor:
                cid = self.__map_sensor[cid]
            else:
                self.__warning("not importing resource referencing non-existing sensor " + cid)
                return None, None
        elif ctype == "schedules":
            if cid in self.__map_schedule:
                cid = self.__map_schedule[cid]
            else:
                self.__warning("not importing resource referencing non-existing schedule " + cid)
                return None, None
        elif ctype == "rules":
            if cid in self.__map_rule:
                cid = self.__map_rule[cid]
            else:
                self.__warning("not importing resource referencing non-existing rule " + cid)
                return None, None
        elif ctype == "scenes":
            if cid in self.__map_scene:
                cid = self.__map_scene[cid]
            else:
                self.__warning("not importing resource referencing non-existing scene " + cid)
                return None, None
        elif ctype != "config":
            self.__error("unsupported resource type in " + address)
            return None, None
        if with_api:
            address = "/api/" + self.apiKey + "/" + ctype + "/" + cid
        else:
            address = "/" + ctype + "/" + cid
        if match.group(4):
            address = address + match.group(4)
        return address, ctype
    
    def __mapAction(self, action, with_api):
        """
        Map action from old system to new system or return None if not possible
        """
        caddress = action["address"]
        cbody = action["body"]
        caddress, ctype = self.__mapAddress(caddress, with_api)
        if not caddress:
            return None
        action["address"] = caddress
        if ctype == "groups":
            # command addressing group, so maybe needs to fix scene in body
            if "scene" in cbody:
                sid = cbody["scene"]
                if sid in self.__map_scene:
                    action["body"]["scene"] = self.__map_scene[sid]
                else:
                    self.__warning("not importing resource referencing non-existing scene " + sid)
                    return None
        return action

    def __restoreSchedules(self):
        """
        Restore schedules and build mapping of schedules from original bridge to this bridge into __map_schedule
        """
        s = self.__current["schedules"]
        t = self.__target["schedules"]
        # build index of schedules by name in the source bridge
        nameidx = {}
        for index, data in s.items():
            if data["name"] in nameidx:
                self.__error("duplicate schedule name " + data["name"])
            nameidx[data["name"]] = index
        tnameidx = {}
        for index, data in t.items():
            name = data["name"]
            if name in tnameidx:
                self.__error("duplicate schedule name " + name + " at index " + index + " and " + tnameidx[name])
            tnameidx[name] = index
 
            command = self.__mapAction(data["command"], True)
            if not command:
                self.__warning("not importing schedule " + name + " referencing non-existing item")
                continue

            body = {"name" : name, "description": data["description"], "command": command,
                    "status": data["status"], "localtime": data["localtime"]}
            if "autodelete" in data:
                body["autodelete"] = data["autodelete"]
            
            # find whether the schedule already exists in this bridge and if it does, update the old one
            idx = None
            if name in nameidx:
                # yes, it exists, update schedule
                idx = nameidx[name]
                if s[idx]["recycle"] != data["recycle"]:
                    self.__error("schedule " + name + " has different recycle flag, expected " + data["recycle"])
                print("   - updating schedule " + name + '/' + idx)
                self.__put("schedules/" + idx, body)
            else:
                # create a new schedule                
                body["recycle"] = data["recycle"]
                print("   - creating schedule " + name + ": " + str(body))
                idx = self.__post("schedules", body)
            self.__map_schedule[index] = idx
        print("   - schedule map: " + str(self.__map_schedule))
   
    def __restoreRules(self):
        """
        Restore rules and build mapping of rules from original bridge to this bridge into __map_rule
        """
        s = self.__current["rules"]
        t = self.__target["rules"]
        # build index of rules by name in the source bridge
        nameidx = {}
        for index, data in s.items():
            if data["status"] == "resourcedeleted":
                continue
            if data["name"] in nameidx:
                self.__error("duplicate rule name " + data["name"])
            nameidx[data["name"]] = index
        tnameidx = {}
        for index, data in t.items():
            if data["status"] == "resourcedeleted":
                continue
            name = data["name"]
            if name in tnameidx:
                self.__error("duplicate rule name " + name + " at index " + index + " and " + tnameidx[name])
            tnameidx[name] = index
 
            conditions = []
            actions = []
            error = False
            for c in data["conditions"]:
                # map one condition
                caddr, ctype = self.__mapAddress(c["address"], False)
                if caddr:
                    c["address"] = caddr
                    conditions.append(c)
                else:
                    error = True
                    break
            if error:
                continue
            for a in data["actions"]:
                # map one action
                a = self.__mapAction(a, False)
                if a: 
                    actions.append(a)
                else:
                    error = True
                    break
            if error:
                continue
            body = {"name" : name, "status": data["status"], "conditions": conditions, "actions": actions}
            
            # find whether the rule already exists in this bridge and if it does, update the old one
            idx = None
            if name in nameidx:
                # yes, it exists, update rule
                idx = nameidx[name]
                if s[idx]["recycle"] != data["recycle"]:
                    self.__error("rule " + name + " has different recycle flag, expected " + data["recycle"])
                print("   - updating rule " + name + '/' + idx)
                self.__put("rules/" + idx, body)
            else:
                # create a new rule                
                body["recycle"] = data["recycle"]
                print("   - creating rule " + name + ": " + str(body))
                idx = self.__post("rules", body)
            self.__map_rule[index] = idx
        print("   - rule map: " + str(self.__map_rule))
    
    def __restoreResourceLinks(self):
        """
        Restore resource links and build mapping of resource links from original bridge to this bridge into __map_resource_links
        """
        s = self.__current["resourcelinks"]
        t = self.__target["resourcelinks"]
        # build index of resource links by name in the source bridge
        nameidx = {}
        for index, data in s.items():
            if data["name"] in nameidx:
                self.__error("duplicate resource link name " + data["name"])
            nameidx[data["name"]] = index
        tnameidx = {}
        for index, data in t.items():
            name = data["name"]
            if name in tnameidx:
                self.__error("duplicate resource link name " + name + " at index " + index + " and " + tnameidx[name])
            tnameidx[name] = index
 
            links = []
            missing_links = []
            makes_sense = False
            for l in data["links"]:
                cl, ctype = self.__mapAddress(l, False)
                if cl:
                    links.append(cl)
                    if ctype == "rules":
                        makes_sense = True
                else:
                    missing_links.append(l)
            if len(links) == 0:
                self.__warning("not importing resource link " + name + " with no links")
                continue
            if not makes_sense:
                if name in nameidx:
                    # drop the link
                    print("   - deleting resource link " + name + " without any rules")
                    self.__delete("resourcelinks/" + nameidx[name])
                else:
                    self.__warning("not importing resource link " + name + " without any rules")
                continue
            if len(missing_links) > 0:
                self.__warning("resource link " + name + " is missing linked resources " + str(missing_links))
            body = {"name" : name, "description": data["description"], "classid": data["classid"], "links": links}
            
            # find whether the resource link already exists in this bridge and if it does, update the old one
            idx = None
            if name in nameidx:
                # yes, it exists, update rule
                idx = nameidx[name]
                if s[idx]["recycle"] != data["recycle"]:
                    self.__error("resource link " + name + " has different recycle flag, expected " + data["recycle"])
                print("   - updating resource link " + name + '/' + idx)
                self.__put("resourcelinks/" + idx, body)
            else:
                # create the resource link                
                body["recycle"] = data["recycle"]
                print("   - creating resource link " + name + ": " + str(body))
                idx = self.__post("resourcelinks", body)
            self.__map_resource_links[index] = idx
        print("   - resource link map: " + str(self.__map_resource_links))
        
    def __isRelevantAddress(self, address, with_api):
        # Check if the address addresses a light or light group
        match = None
        if with_api:
            match = MATCH_SCHEDULE_ADDRESS.match(address)
        else:
            match = MATCH_RULE_ADDRESS.match(address)
        if not match:
            self.__error("unknown schedule/rule address " + address)
        ctype = match.group(2)
        if ctype == "lights":
            return True
        if ctype == "groups":
            return match.group(3) != "0"
        return False

    def __cleanupResourceLinks(self):
        t = self.__target["resourcelinks"]
        for key, data in t.items():
            if key not in self.__map_resource_links:
                continue
            print("   - checking " + data["name"])
            key = self.__map_resource_links[key]
            data = self.__get("resourcelinks/" + key)
            links = data["links"]
            relevant = False
            for l in links:
                if relevant:
                    break
                match = MATCH_RESOURCE_LINK.match(l)
                if not match:
                    self.__warning("Resource link " + l + " doesn't conform to link format for " + data["name"])
                    continue
                rtype = match.group(1)
                rkey = match.group(2)
                if rtype == "rules":
                    rule = self.__get("rules/" + rkey)
                    for a in rule["actions"]:
                        addr = a["address"]
                        if self.__isRelevantAddress(addr, False):
                            print("   - relevant address " + addr + " in rule " + rkey)
                            relevant = True
                            break
                elif rtype == "schedules":
                    schedule = self.__get("schedules/" + rkey)
                    addr = schedule["command"]["address"]
                    if self.__isRelevantAddress(addr, True):
                        print("   - relevant address " + addr + " in schedule " + rkey)
                        relevant = True
                        break
                else:
                    # ignore other types
                    continue
            if not relevant:
                print("   - dropping non-relevant resource link " + data["name"])
                self.__delete("resourcelinks/" + key)
        
    def __make_map(self, source):
        m = {}
        for index, data in source.items():
            if "uniqueid" in data.keys():
                if data["uniqueid"] in m:
                    self.__error("duplicate uniqueid " + data["uniqueid"])
                m[data["uniqueid"]] = index
            elif data["name"] != "Daylight":
                self.__error("missing uniqueid for index " + index)
        return m

    def __schedule_put(self, resource, data):
        self.__updates.append([resource, data])
    
    def __run_updates(self):
        print("   - UPDATING the bridge")
        for action in self.__updates:
            resource = action[0]
            data = action[1]
            self.__put(resource, data)
        self.__updates = []

    def __put(self, resource, data):
        tmp = requests.put(self.urlbase + '/' + resource, json=data)
        if tmp.status_code != 200:
            print("Data:", data)
            raise Exception("Cannot put " + resource + ": " + tmp.text)
        result = json.loads(tmp.text)[0];
        if not "success" in result:
            print("Data:", data)
            raise Exception("Cannot put " + resource + ": " + tmp.text)

    def __post(self, resource, data):
        tmp = requests.post(self.urlbase + '/' + resource, json=data)
        if tmp.status_code != 200:
            print("Data:", data)
            raise Exception("Cannot post " + resource + ": " + tmp.text)
        result = json.loads(tmp.text)[0];
        if not "success" in result:
            print("Data:", data)
            raise Exception("Cannot post " + resource + ": " + tmp.text)
        if "id" in result["success"]:
            return result["success"]["id"]
        elif "address" in result["success"]:
            return result["success"]["address"]
        else:
            raise Exception("Unknown success response: " + str(result))

    def __delete(self, resource):
        tmp = requests.delete(self.urlbase + '/' + resource)
        if tmp.status_code != 200:
            raise Exception("Cannot delete " + resource + ": " + tmp.text)
        result = json.loads(tmp.text)[0];
        if not "success" in result:
            raise Exception("Cannot delete " + resource + ": " + tmp.text)

    def __error(self, msg):
        print("   - ERROR: " + msg)
        self.__errors.append(msg)
        
    def __warning(self, msg):
        print("   - WARNING: " + msg)
