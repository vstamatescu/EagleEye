#!/usr/bin/env python2
#
# Project Eagle Eye
# Group 3 - UniSA 2015
# Gwilyn Saunders & Kin Kuen Liu
# version 0.2.10
# 

import cv2, xml.etree.ElementTree as ET, numpy as np

class Mapper:
    def __init__(self, intrinsic, trainer, cfg):
        # variables
        self.rv = np.asarray([], dtype=np.float32)  # rotation
        self.tv = np.asarray([], dtype=np.float32)  # translation
        
        # load some configs, required by solvePnP eventually
        #self.cfg = cfg
        
        # open intrinsic, trainer files
        self.cam, self.distort = self.parseCamIntr(intrinsic)
        self.img_pts, self.obj_pts = self.parseTrainer(trainer)
        
        print "img_pts {}".format(len(self.img_pts))
        print "obj_pts {}".format(len(self.obj_pts))
        
        #calculate pose
        self.rv, self.tv = self.calPose(mode=0)
    
    # opens the Intrinsic calib xml file
    def parseCamIntr(self, xmlpath):
        if xmlpath is None:
            raise IOError('Invalid file path to XML file.')
        
        cm_dict = {'fx': None, 'fy': None, 'cx': None, 'cy': None}
        dc_dict = {'k1': 0.0, 'k2': 0.0,
                   'k3': 0.0, 'k4': 0.0,
                   'k5': 0.0, 'k6': 0.0,
                   'p1': 0.0, 'p2': 0.0,
                   'c1': 0.0, 'c2': 0.0,
                   'c3': 0.0, 'c4': 0.0
                   }
        
        cm, dc = [], []
        
        tree = ET.parse(xmlpath)
        root = tree.getroot()
        
        if len(root) == 0:
            raise IOError('XML file is empty.')
        
        for elem in root.iter():
            if elem.tag == 'CamMat':
                cm_dict.update(elem.attrib)
            if elem.tag =='DistCoe':
                dc_dict.update(elem.attrib)
            
        ### TODO: CHECK None Values !!!!
        
        if cm_dict['fx'] and cm_dict['fy'] and cm_dict['cx'] and cm_dict['cy'] is not None:
            # build a 3x3 camera matrix
            cm = np.matrix([[float(cm_dict['fx']), 0, float(cm_dict['cx'])],
                            [0, float(cm_dict['fy']), float(cm_dict['cy'])],
                            [0, 0, 1]
                            ])
            
        if cv2.__version__ >= '3.0.0':
            dc = np.asarray([float(dc_dict['k1']), float(dc_dict['k2']),
                                float(dc_dict['p1']), float(dc_dict['p2']),
                                float(dc_dict['k3']), float(dc_dict['k4']),
                                float(dc_dict['k5']), float(dc_dict['k6']),
                                float(dc_dict['c1']), float(dc_dict['c2']),
                                float(dc_dict['c3']), float(dc_dict['c4'])
                            ])
        else:
            dc = np.asarray([float(dc_dict['k1']), float(dc_dict['k2']),
                                float(dc_dict['p1']), float(dc_dict['p2']),
                                float(dc_dict['k3']), float(dc_dict['k4']),
                                float(dc_dict['k5']), float(dc_dict['k6'])
                            ])
        return cm, dc
    
    
    def parseTrainer(self, xmlpath):
        if xmlpath is None:
            raise IOError('Invalid file path to XML file.')
        
        tree = ET.parse(xmlpath)
        root = tree.getroot()
        
        if len(root) == 0:
                raise IOError('XML file is empty.')
        
        frames = root.find('frames')
        self.num_training = int(frames.attrib["num"])
        
        img_pos = []
        obj_pos = []
        
        for f in frames:
            # TODO: inconsistent get attrib names ??
            plane = f.find('plane').attrib
            vicon = f.find('vicon').attrib
            visibility = f.find('visibility').attrib
            
            x = float(plane['x'])
            y = float(plane['y'])
            vicon_x = float(vicon['x'])
            vicon_y = float(vicon['y'])
            vicon_z = float(vicon['z'])
            
            img_pos.append((x, y))
            obj_pos.append((vicon_x, vicon_y, vicon_z))
        
        return np.asarray(img_pos, dtype=np.float32), np.asarray(obj_pos, dtype=np.float32)
    
    
    def calPose(self, mode=0):
        if len(self.img_pts) < 4 or len(self.obj_pts) < 4:
            raise Exception("Must have at least 4 training points.")
            
        if len(self.img_pts) != len(self.obj_pts):
            raise Exception("Training image points and object points must be equal in size. "
                            "image pts {}, obj pts {}".format(len(self.img_pts), len(self.obj_pts)))
        
        # TODO: customised solvePnP flags from config
        # levenberg-marquardt iterative method
        if mode == 0:
            retval, rv, tv = cv2.solvePnP(
                                self.obj_pts, self.img_pts, 
                                self.cam, self.distort,
                                None, None, cv2.SOLVEPNP_ITERATIVE)
            '''
            NOT RUNNING
            http://stackoverflow.com/questions/30271556/opencv-error-through-calibration-tutorial-solvepnpransac
            rv, tv, inliners = cv2.solvePnPRansac(
                                self.obj_pts, self.img_pts, 
                                self.cam, self.distort)
            '''
        # alternate, loopy style iterative method (could be the same, idk)
        else:
            rv, tv = None, None
            for i in range(0, len(data)):
                retval, _rv, _tv = cv2.solvePnP(
                                    self.obj_pts[i], self.img_pts[i],
                                    self.cam, self.distort,
                                    rv, tv, useExtrinsicGuess=True)
                #append if 'good'
                if retval: 
                    rv, tv = _rv, _tv
        
        # check, print, return
        if rv is None or rv is None or not retval:
            raise Exception("Error occurred when calculating rotation and translation vectors.")
        
        print 'Rotation Vector:\n', rv
        print 'Translation Vector:\n', tv
        
        return rv, tv
    
    
    def reprojpts(self, obj_pts):
        #if len(obj_pts) == 0:
        #    raise Error('No points to project.')
        
        proj_imgpts, jac = cv2.projectPoints(np.asarray([obj_pts], dtype=np.float32), self.rv, self.tv, self.cam, self.distort)
        proj_imgpts = proj_imgpts.reshape((len(proj_imgpts), -1))
        
        #print 'Project Point Coordinates:'
        #for n in range(0, len(proj_imgpts)):
        #    print 'Point', n+1, ':', proj_imgpts[n]
        
        return proj_imgpts[0]

