# 
# Project Eagle Eye
# Group 15 - UniSA 2015
# 
# Gwilyn Saunders
# version 0.2.11
# 
# Reads an XML Dataset file into memory
# Provides synchronisation techniques - via setRatio()
# 

import xml.etree.ElementTree as ET
from math import ceil, floor
from theta_sides import Theta

class Xmlset:
    off_by_mov = 0
    off_by_csv = 1
    modes = ["trainer", "mapper", "annotated"]
    mode = "trainer"
    
    @staticmethod
    def offset_mode(var):
        if 'csv' in var: return Xmlset.off_by_csv
        else: return Xmlset.off_by_mov
    
    def __init__(self, path=None, offset=0, offmode=off_by_csv, readmode="trainer"):
        self.offset = offset
        self.offmode = offmode
        if path is not None:
            self.open(path)
        
        # TODO: this is unused, what is this for??
        if readmode not in self.modes:
            print "Read mode:", readmode, "is not supported, changing to default to read", self.mode
        else:
            self.mode = readmode
    
    def open(self, path):
        self.path = path
        tree = ET.parse(path)
        self.root = tree.getroot()
        
        if len(self.root) == 0:
            raise IOError('XML file is empty.')
        
        if self.root.tag != "dataset":
            raise IOError("Wrong input file, needs a dataset xml file.")
        
        self._frames = {}
        self._at = None
        self._ratio = 1.0
        
        for frm in self.root.findall('frameInformation'):
            num = int(frm.find('frame').attrib['number'])
            if self._at is None:
                self._at = num
            
            objects = {}
            for obj in frm.findall('object'):
                name = obj.attrib['name']
                objects[name] = {}
                objects[name]["box"] = obj.find('boxinfo').attrib
                objects[name]["centre"] = obj.find('centroid').attrib
                
                visible = obj.find("visibility")
                if visible is not None:
                    objects[name]["visibility"] = visible.attrib
                    
                if 'lens' in obj.attrib:
                    objects[name]["lens"] = Theta.resolve(obj.attrib['lens'])
                else:
                    objects[name]["lens"] = Theta.NonDual
            
            self._frames[num] = objects
        
        self.total = len(self._frames)
    
    # Gets current frame, or a specific frame if 'at' option is > 0
    def data(self, at=-1, mode=0):
        at = int(at)
        
        if at == -1:
            at = self.at(mode)
        
        # if failed to find, return None
        if at not in self._frames.keys():
            return None
        
        return self._frames[at]
    
    def next(self):
        i = self._at + self._ratio
        if i < self.total and i < self.total-1: # what?
            self._at = i
            return True
        return False
            
    def back(self):
        i = self._at - self._ratio
        if i >= 0:
            self._at = i
            return True
        return False
    
    def at(self, mode=0):
        if mode == 0:
            return int(round(self._at, 0)) + self.offset
        if mode == 1:
            return int(ceil(self._at)) + self.offset
        else:
            return int(floor(self._at)) + self.offset
    
    def ratio(self):
        return self._ratio
    
    # calculate appropriate ratio from the matching video frames
    def setRatio(self, video_frames):
        self._ratio = self.total / float(video_frames)
    
    def resetRatio(self):
        self._ratio = 1.0
    
    def status(self):
        return "{}/{}".format(self.at(), self.total)
    
