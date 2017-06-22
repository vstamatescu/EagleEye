import os, time, cv2, glob, math, h5py, datetime, xml.etree.ElementTree as ET, numpy as np
from theta_sides import Theta
from scipy.optimize import least_squares

magnitude = lambda x: np.sqrt(np.vdot(x, x))
unit = lambda x: x / magnitude(x)


class Calibrator:
	def __init__(self, imgPoints, objPoints, imgPointsAbs, imgs, xc, yc):
		np.set_printoptions(linewidth=200, threshold='inf')
		self.imgs = imgs
		self.xc = xc
		self.yc = yc
		#self.xc = 480
		#self.yc = 540
		print 'xc:', self.xc
		print 'yc:', self.yc

		self.c = 1
		self.d = 0
		self.e = 0

		#USE BACKSIDE .H5 POINTS OR FIND THEM IN CHESSBOARDS USING OCV
		self.img_pts, self.obj_pts, self.imgAbs = imgPoints, objPoints, imgPointsAbs #self.getPointsH5() #img_pts already have centre subtracted

		#build absolute image points (no centre subtraction
		self.XpAbs = np.array([p[1] for i in self.imgAbs for p in i]) #x, y swap done here with indices
		self.XpAbs = np.array(np.split(self.XpAbs, len(self.imgAbs)))
		self.YpAbs = np.array([p[0] for i in self.imgAbs for p in i])
		self.YpAbs = np.array(np.split(self.YpAbs, len(self.imgAbs)))

		self.Xp = np.array([p[0] for i in self.img_pts for p in i]) #x, y swap NOT done here, as already done
		self.Yp = np.array([p[1] for i in self.img_pts for p in i])
		self.Xp = np.array(np.split(self.Xp, len(self.img_pts))) #split into each image
		self.Yp = np.array(np.split(self.Yp, len(self.img_pts)))
		self.Xt = np.asarray([p[0] for p in self.obj_pts[0]])
		self.Yt = np.asarray([p[1] for p in self.obj_pts[0]])

		print "img_pts {}".format(len(self.img_pts))
		print "obj_pts {}".format(len(self.obj_pts))
		print 'shape img_pts: ', np.shape(self.img_pts)
		print 'shape obj_pts: ', np.shape(self.obj_pts)

		#print 'img_pts:\n', self.img_pts
		#print 'obj_pts:\n', self.obj_pts
		#print 'Xp:', self.Xp.shape, '\n', self.Xp
		#print 'Yp:', self.Yp.shape, '\n', self.Yp

		self.taylorOrder = 4

		# calculate pose
		self.RRfin, self.ss = self.calPose(self.img_pts, self.obj_pts, 9*6) #TODO: remove hardcoded grid dim 9*6
		self.meanErr = 0
		self.MSE = 0
		#self.ss = np.array([-216.63, 0, -0.00018466, 4.7064e-06, -5.0066e-09])
		#self.RRfin, self.ss = self.getMLRRfinSS() #matlab's RRfin and ss

		#print 'RRfin:\n', self.RRfin
		print 'SS:\n', self.ss
		print 'yc:', self.yc, '  xc:', self.xc
		print 'c, d, e:', self.c, self.d, self.e
		self.reprojectPoints(self.ss, self.RRfin)
		self.bundleAdjustmentUrban(self.c, self.d, self.e)

		#print 'RRfinAfterOpt:\n', self.RRfin
		print 'ssAfterOp:', self.ss
		print 'yc:', self.yc, '  xc:', self.xc
		print 'c, d, e:', self.c, self.d, self.e
		self.reprojectPoints(self.ss, self.RRfin)

	def bundleAdjustmentUrban(self, c, d, e):
		print 'STARTING NONLINEAR REFINEMENT'

		ss0 = self.ss
		x0 = np.array([1, 1, 1, 0, 0])
		x0 = np.append(x0, np.ones(len(ss0)))

		offset = 6 + self.taylorOrder
		for i in range(len(self.img_pts)):
			R = np.copy(self.RRfin[i])
			R = np.transpose(R)
			R[2] = np.cross(R[0], R[1])
			R = np.transpose(R)
			r = np.array(cv2.Rodrigues(R)[0])
			r = np.reshape(r, (3,))
			t = np.transpose(self.RRfin[i])[2]
			#print 'i:', i

			x0 = np.append(x0, [r[0], r[1], r[2], t[0], t[1], t[2]])

		#print 'xo b4:\n', x0
		x0 = least_squares(self.bundleErrUrban, x0, ftol=1e-4, xtol=1e-5) #TODO: can't set max iterations?
		x0 = x0['x']
		#print 'x0Aft:\n', x0

		RRfinOpt = np.zeros(self.RRfin.shape)
		lauf = 0

		for i in range(len(self.img_pts)):
			RRfinOpt[i] = cv2.Rodrigues(np.array([x0[offset+lauf], x0[offset+1+lauf], x0[offset+2+lauf]]))[0]
			RRfinOpt[i][0][2] = x0[offset+3+lauf]
			RRfinOpt[i][1][2] = x0[offset+4+lauf]
			RRfinOpt[i][2][2] = x0[offset+5+lauf]
			lauf += 6


		ssc = x0[5:offset]
		self.ss = ss0 * np.transpose(ssc)
		self.xc *= x0[1]
		self.yc *= x0[0]
		self.c = x0[2]
		self.d = x0[3]
		self.e = x0[4]

		#print 'xc:', self.xc
		#print 'yc:', self.yc
		#print 'c, d, e:', self.c, self.d, self.e
		self.RRfin = RRfinOpt

	def bundleErrUrban(self, x):
		M = np.vstack((self.Xt, self.Yt, np.zeros(self.Xt.shape)))

		a = x[0]
		b = x[1]
		c = x[2]
		d = x[3]
		e = x[4]

		offset = self.taylorOrder+6
		ssc = x[5:offset]
		num_points = len(M[0])

		Mc = []
		Xpp = []
		Ypp = []
		lauf = 0

		for i in range(len(self.imgs)):
			R = cv2.Rodrigues(np.array([x[offset+lauf], x[offset+1+lauf], x[offset+2+lauf]]))[0]
			T = np.array([x[offset+3+lauf], x[offset+4+lauf], x[offset+5+lauf]])
			T = np.reshape(T, (len(T), 1))

			toAppend = np.transpose(np.matmul(R, M) + T*np.ones(num_points))
			if i == 0: #Change shape so we can stack
				Mc = np.zeros(len(toAppend[0]))
				Xpp = np.zeros(len(self.Xp[0]))
				Ypp = np.zeros(len(self.Yp[0]))
			Mc = np.vstack((Mc, toAppend))

			Xpp = np.vstack((Xpp, self.Xp[i]+self.yc))
			Ypp = np.vstack((Ypp, self.Yp[i]+self.xc))

			if i == 0: # delete zeroes we added
				Mc = np.delete(Mc, 0, 0)
				Xpp = np.delete(Xpp, 0, 0)
				Ypp = np.delete(Ypp, 0, 0)

			lauf += 6

		#print 'Mc:\n', Mc
		#print 'McT:\n', np.transpose(Mc)

		#print 'Xpp:\n', Xpp
		#print 'Ypp:\n', Ypp

		#print 'ss:\n', self.ss
		#print 'np.transpor(ssc):\n', np.transpose(ssc)

		xp1, yp1 = self.omni3d2pixel(self.ss * np.transpose(ssc), np.transpose(Mc))

		#print 'xp1Shape:', xp1.shape, 'yp1Shape:', yp1.shape
		#print 'xp1:', xp1, '\nyp1:', yp1

		#print 'xc:', self.xc
		#print 'yc:', self.yc

		xp = xp1*c + yp1*d + self.yc*a
		yp = xp1*e + yp1 + self.xc*b

		#print 'xpshape:\n', xp.shape
		#print 'xp:\n', xp
		#print 'ypshape:\n', yp.shape
		#print 'yp:\n', yp

		#print 'Xpp:\n', Xpp.shape, '\n', Xpp
		#print 'xp:\n', xp.shape, '\n', xp

		Xpp = Xpp.flatten()
		Ypp = Ypp.flatten()

		errx = Xpp - np.transpose(xp)
		erry = Ypp - np.transpose(yp)
		errW = np.array([])
		errW = np.append(errW, errx)
		errW = np.append(errW, erry)

		#print 'errx:\n', errx
		#print 'erry:\n', erry
		#print 'errW:\n', errW
		#print 'InX:', datetime.datetime.now().microsecond

		return errW

	def reprojectPoints(self, ss, RRfin):
		print 'REPROJECTING'

		err = np.zeros(len(self.img_pts))
		stderr = np.zeros(len(self.img_pts))
		MSE = 0
		counter = -1

		Xt = np.asarray([p[0] for p in self.obj_pts[0]])
		Yt = np.asarray([p[1] for p in self.obj_pts[0]])
		#Xt = Xt.reshape(len(Xt), 1)
		#Yt = Yt.reshape(len(Yt), 1)
		#print 'Xt:\n', Xt
		#print 'Yt:\n', Yt

		xx2 = np.vstack((Xt, Yt, np.ones((len(Xt)))))
		#print 'xx2: ', xx2.shape, '\n', xx2

		for imgi in range(len(self.img_pts)):
			#print 'IMG:', imgi
			counter += 1
			#print 'RRfin[imgi]: ', RRfin[imgi].shape, '\n', RRfin[imgi]
			xx = np.matmul(RRfin[imgi], xx2)
			#print 'xx', xx.shape, '\n', xx
			x, y = self.omni3d2pixel(ss, xx)
			# Apply affine transformation, which includes adding centre of distortion
			XpReproj = x*self.c + y*self.d + self.yc
			YpReproj = x*self.e + y + self.xc
			#print 'XpReproj:', XpReproj.shape, '\n', XpReproj
			#print 'YpReproj:', YpReproj.shape, '\n', YpReproj

			stt = np.sqrt((self.XpAbs[imgi] - XpReproj)**2 + (self.YpAbs[imgi] - YpReproj)**2)
			err[counter] = np.mean(stt)
			stderr[counter] = np.std(stt)
			MSE += np.sum((self.XpAbs[imgi] - XpReproj)**2 + (self.YpAbs[imgi] - YpReproj)**2)

			#uncomment all this to see points drawn on chessboards
			#h, w = self.imgs[imgi].shape[:2]
			#yc = h / 2  # 480
			#xc = w / 2  # 540

			#for p in range(len(self.Xp[imgi])):
			#	cv2.circle(self.imgs[imgi], (int(round(self.Yp[imgi][p]+xc)), int(round(self.Xp[imgi][p]+yc))), 3, (0, 0, 255), -1)
			#	cv2.circle(self.imgs[imgi], (int(round(YpReproj[p]+xc)), int(round(XpReproj[p]+yc))), 2, (0, 255, 0), -1)
			#	cv2.circle(self.imgs[imgi], (xc, yc), 3, (0, 255, 255), -1)
			#cv2.namedWindow('sphere', cv2.WINDOW_AUTOSIZE)
			#cv2.imshow('sphere', self.imgs[imgi])
			#cv2.waitKey(0)

		print 'AVERAGE REPROJECTION ERROR COMPUTED FOR EACH CHESSBOARD'
		for i in range(len(err)):
			print 'Err: ', err[i], 'std: ', stderr[i]

		print 'TOTAL AVERAGE ERROR: ', np.mean(err)
		print 'SUM OF SQUARED ERRORS: ', MSE
		self.meanErr = np.mean(err)
		self.MSE = MSE

	def omni3d2pixel(self, ss, xx):

		eps = np.spacing(1)
		for i in range(len(xx[0])):
			if xx[0][i] == 0 and xx[1][i] == 0:
				xx[0][i] = eps
				xx[1][i] = eps

		m = xx[2] / np.sqrt(xx[0]**2 + xx[1]**2)
		#print 'M: ', m.shape, '\n', m #correct

		rho = np.zeros(len(m))
		polyCoef = ss[::-1]
		#print 'pc:', polyCoef
		polyCoefTemp = np.copy(polyCoef)

		for j in range(len(m)):
			polyCoefTemp[-2] = polyCoef[-2]-m[j]
			#print 'pct:', j, polyCoefTemp
			rhoTmp = np.roots(polyCoefTemp)
			#print 'rhoTmp:', j, rhoTmp
			res = rhoTmp[np.logical_and(np.imag(rhoTmp) == 0, rhoTmp > 0)]
			#print 'res:', j, res
			if len(res) == 0:
				rho[j] = np.nan
			elif len(res) > 1:
				rho[j] = min(res)
			else:
				rho[j] = res[0]

		x = xx[0] / np.sqrt(xx[0]**2 + xx[1]**2) * rho
		y = xx[1] / np.sqrt(xx[0]**2 + xx[1]**2) * rho
		return x, y

	def calPose(self, imgPts, objPts, ppp): #ppp=pointsPerPattern

		print 'running calPose...'

		RRfin = np.zeros((len(imgPts), 3, 3))
		for imgi in range(len(imgPts)):
			#print 'imgi: ', imgi
			A = np.ones((ppp, 6))
			for pti in range(len(imgPts[imgi])): #assume len(imgPts)==len(objPts)
				Xt = objPts[imgi][pti][0]
				Yt = objPts[imgi][pti][1]
				Xpt = imgPts[imgi][pti][0]
				Ypt = imgPts[imgi][pti][1]
				A[pti][0] = Xt * Ypt
				A[pti][1] = Yt * Ypt
				A[pti][2] = -Xt * Xpt
				A[pti][3] = -Yt * Xpt
				A[pti][4] = Ypt
				A[pti][5] = -Xpt

			#print 'A:\n', A

			(U, S, V) = np.linalg.svd(A)
			V = V.T
			#print 'V:\n', V

			R11 = V[0][len(V[0])-1]
			R12 = V[1][len(V[1])-1]
			R21 = V[2][len(V[2])-1]
			R22 = V[3][len(V[3])-1]
			T1 = V[4][len(V[4])-1]
			T2 = V[5][len(V[5])-1]

			AA = (R11*R12 + R21*R22)**2
			BB = R11**2 + R21**2
			CC = R12**2 + R22**2
			R32_2 = np.roots([1, CC-BB, -AA])
			#print 'R32_2: ', R32_2
			R32_2  = [r for r in R32_2 if r >= 0] #roots > 0

			'''
			print 'R11: ', R11
			print 'R12: ', R12
			print 'R21: ', R21
			print 'R22: ', R22
			print 'T1: ', T1
			print 'T2: ', T2
			print 'AA: ', AA
			print 'BB:', BB
			print 'CC: ', CC
			print 'R32_2: ', R32_2
			'''

			R31 = []
			R32 = []
			sg = [1, -1]

			for i in range(len(R32_2)): #TODO: is this ever len!=1||2? Doesn't make sense if not
				for j in [0, 1]:
					sqrtR32_2 = sg[j] * math.sqrt(R32_2[i])
					R32.append(sqrtR32_2)
					if R32_2[0] == 0 or ( len(R32_2) == 2 and R32_2[0] == 0 and R32_2[1] == 0 ):
						R31.append(math.sqrt(CC-BB))
						R31.append(-math.sqrt(CC-BB))
						R32.append(sqrtR32_2)
					else:
						R31.append((R11*R12 + R21*R22) / -sqrtR32_2)


			#shape different from Ocam's
			RR = np.zeros((len(R32)*2, 3, 3)) #[ [ [0, 0, 0], [0, 0, 0], [0, 0, 0] ], ... ]
			#print 'R31:\n', R31
			#print 'R32:\n', R32
			count = -1 #0 in matlab
			for i1 in range(len(R32)):
				for i2 in range(2):
					count += 1
					Lb = math.sqrt(1 / (R11**2 + R21**2 + R31[i1]**2))
					RR[count] = sg[i2] * Lb * np.array([ [R11, R12, T1], [R21, R22, T2], [R31[i1], R32[i1], 0] ])

			#print 'RR:\n', RR

			RR1 = []
			minRR = float('inf')
			minRR_ind = -1
			Xpt = imgPts[imgi][0][0] #TODO: why use only first point on chessboard?
			Ypt = imgPts[imgi][0][1]
			#print 'Xpt: ', Xpt, ', Ypt: ', Ypt
			for min_count in range(len(RR)):
				toNorm = [ np.subtract( [ [ RR[min_count][0][2] ], [ RR[min_count][1][2] ] ], [ [Xpt], [Ypt] ] ) ]
				#print 'toNorm', min_count, ': \n', toNorm
				#print 'Norm', min_count, ': ', np.linalg.norm(toNorm)
				if np.linalg.norm(toNorm) < minRR:
					minRR = np.linalg.norm(toNorm)
					minRR_ind = min_count

			#print 'RR:', imgi, '\n', RR
			if minRR_ind != -1:
				count2 = -1
				for count in range(len(RR)):
					if np.sign(RR[count][0][2]) == np.sign(RR[minRR_ind][0][2]) and np.sign(RR[count][1][2]) == np.sign(RR[minRR_ind][1][2]):
						count2 += 1
						RR1.append(RR[count])

			if len(RR1) == 0:
				RRfin = 0
				ss = 0
				return RRfin, ss

			#TODO: stop redefining these
			Xt = np.asarray([p[0] for p in objPts[imgi]])
			Yt = np.asarray([p[1] for p in objPts[imgi]])
			Xpt = np.asarray([p[0] for p in imgPts[imgi]])
			Ypt = np.asarray([p[1] for p in imgPts[imgi]])
			#print 'Xt:\n', Xt
			#print 'Xpt:\n', Xpt
			#print 'Yt:\n', Yt
			#print 'Ypt:\n', Ypt

			nm = self.plot_RR(RR1, Xt, Yt, Xpt, Ypt, 0)

			RRdef = RR1[nm]
			#RRdef[2][2] *= -1
			#print 'RR1:', imgi, '. nm=', nm, '\n', np.asarray(RR1)
			#print 'RRdef:', imgi, '\n', np.asarray(RRdef)
			#print 'RRdef:\n', RRdef
			RRfin[imgi] = RRdef

		#print 'RRfin:\n', RRfin

		RRfin, ss = self.omni_find_parameters_fun(objPts, imgPts, RRfin, self.taylorOrder, len(imgPts))
		return RRfin, ss

	def plot_RR(self, RR, Xt, Yt, Xpt, Ypt, figure_number):

		index = -1
		for i in range(len(RR)):
			RRdef = RR[i]
			R11 = RRdef[0][0]
			R21 = RRdef[1][0]
			R31 = RRdef[2][0]
			R12 = RRdef[0][1]
			R22 = RRdef[1][1]
			R32 = RRdef[2][1]
			T1 = RRdef[0][2]
			T2 = RRdef[1][2]

			MA = R21*Xt + R22*Yt + T2
			MB = Ypt * (R31*Xt + R32*Yt)
			MC = R11*Xt + R12*Yt + T1
			MD = Xpt * (R31*Xt + R32*Yt)
			rho = np.sqrt(Xpt**2 + Ypt**2)
			rho2 = Xpt**2 + Ypt**2

			#PP1 = np.array([[MA, MA*rho, MA*rho2, -Ypt], [MC, MC*rho, MC*rho2, -Xpt]])
			#print 'PP1: ', PP1.shape, '\n', PP1

			PP1 = [MA, MA*rho, MA*rho2, -Ypt]
			PP2 = [MC, MC*rho, MC*rho2, -Xpt]
			#print 'PP1:\n', PP1
			#print 'PP2:\n', PP2
			PP3 = np.asarray([np.append(PP1[0], PP2[0]),
							 np.append(PP1[1], PP2[1]),
							 np.append(PP1[2], PP2[2]),
							 np.append(PP1[3], PP2[3])])
			#Make PP the right shape
			PP = []
			for j in range(len(PP3[0])): #assume all PP3 rows same len
				PP.append([PP3[0][j], PP3[1][j], PP3[2][j], PP3[3][j]])
			PP = np.asarray(PP)

			PPinv = np.linalg.pinv(PP)
			QQ = -np.asarray(np.append(MB, MD)) #TODO: need a negative maybe because transpose mistake? It works like this anyways.
			QQ = QQ.reshape(len(QQ), 1)
			#QQ1 = np.asarray(MB)
			#QQ2 = np.asarray(MD)
			#print 'QQ1:\n', QQ1
			#print 'QQ2:\n', QQ2

			#print 'PP: ', PP.shape, '\n', PP
			#print 'PPinv: ', PPinv.shape, '\n', PPinv
			#print 'QQ: ', QQ.shape, '\n', QQ

			s = -np.matmul(PPinv, QQ) #TODO: negative again? Still works fine.
			#print 'S:\n', s
			ss = s[0:3]
			if ss[-1] >= 0:
				index = i

		return index

	def omni_find_parameters_fun(self, objPts, imgPts, RRfin, taylorOrder, imaProc):
		#print 'in ofpf'

		PP = np.zeros((taylorOrder+imaProc, imaProc*len(imgPts[0])*2)) #*2 comes from stacking A, C for each point
		QQ = np.array([])
		count = -1
		initPP1Len = 0
		for imgi in range(imaProc):
			#print 'imgi: ', imgi
			count+=1

			Xt = np.asarray([p[0] for p in objPts[imgi]])
			Yt = np.asarray([p[1] for p in objPts[imgi]])
			Xpt = np.asarray([p[0] for p in imgPts[imgi]])
			Ypt = np.asarray([p[1] for p in imgPts[imgi]])

			RRdef = RRfin[imgi]
			R11 = RRdef[0][0]
			R21 = RRdef[1][0]
			R31 = RRdef[2][0]
			R12 = RRdef[0][1]
			R22 = RRdef[1][1]
			R32 = RRdef[2][1]
			T1 = RRdef[0][2]
			T2 = RRdef[1][2]

			MA = R21 * Xt + R22 * Yt + T2
			MB = Ypt * (R31 * Xt + R32 * Yt)
			MC = R11 * Xt + R12 * Yt + T1
			MD = Xpt * (R31 * Xt + R32 * Yt)

			#print 'MA:\n', MA
			#print 'MB:\n', MB
			#print 'MC:\n', MC
			#print 'MD:\n', MD

			#print 'Xpt:\n', Xpt
			#print 'Ypt:\n', Ypt

			rho = np.zeros((taylorOrder, len(imgPts[0])))
			for j in range(2, taylorOrder+1):
				rho[j-1] = np.sqrt(Xpt**2 + Ypt**2)**j

			#print 'rho:\n', rho

			PP1 = np.array(np.append(MA, MC))
			#print 'PP1:\n', PP1


			for j in range(1, taylorOrder):
				toAppend = np.asarray(np.append(MA*rho[j], MC*rho[j]))
				#print 'toAppend:\n', toAppend
				PP1 = np.vstack((PP1, toAppend))
			#print 'PP1: ', PP1.shape, '\n', PP1

			#print 'PPb4: ', PP.shape, '\n', PP

			if imgi == 0:
				initPP1Len = len(PP1[0])
			start = imgi*initPP1Len #overwrite 0s for t3 vals for that image
			negyxpts = np.append(-Ypt, -Xpt)
			PP[imgi+taylorOrder][start:len(negyxpts)+start] = negyxpts

			for i in range(len(PP1)):
				start = imgi*len(PP1[0])
				PP[i][start:start+len(PP1[i])] = PP1[i]

			#print 'PPaf: ', PP.shape, '\n', PP

			QQ = np.append(QQ, MB)
			QQ = np.append(QQ, MD)

		#print 'QQ: ', QQ.shape, '\n', QQ
		#print 'QQres: ', QQ.reshape(len(QQ), 1).shape, '\n', QQ.reshape(len(QQ), 1)

		PP = self.reshape(PP) #ugh, built it the wrong shape
		#print 'PP: ', PP.shape, '\n', PP
		PPinv = np.linalg.pinv(PP)
		#print 'PPinv: ', PPinv.shape, '\n', PPinv

		QQ = QQ.reshape(len(QQ), 1)
		s = np.matmul(PPinv, QQ)
		#print 's', s
		ss = s[0:taylorOrder]
		count = -1
		for j in range(imaProc):
			count += 1
			RRfin[j][2][2] = s[len(ss)+count]

		ss = ss.reshape(len(ss))
		ss = np.insert(ss, 1, 0)

		#print 'ss: ', ss
		#print 'RRfin:\n', RRfin
		return RRfin, ss

	def isVisible(self, pt):
		pt = np.array(pt).reshape(3, 1)

		RxPt = self.R.dot(pt)
		tv = np.array(self.tv).reshape(3, 1)
		pt_cam = np.add(RxPt, tv).reshape(1, 3)[0]

		# spherical model
		r = np.linalg.norm(pt_cam)
		theta = np.arctan2(pt_cam[1], pt_cam[0])
		phi = np.arccos(-pt_cam[2] / r)
		inv_phi = phi

		# print np.degrees(inv_phi), "<", np.degrees(self.half_fov)
		return inv_phi < self.half_fov

	def reshape(self, mat): #helper function, fixes a mistake

		newMat = np.zeros((len(mat[0]), len(mat)))

		for i in range(len(mat)):
			for j in range(len(mat[0])):
				newMat[j][i] = mat[i][j]

		return newMat

	#TODO: remove all below, debugging
	def getMLRRfinSS(self):
		#in Matlab, use dlmwrite to write out RRfin, then read it in with this.
		#Set ss manually

		ss = np.array([-219.44, 0, 0.0012199, -2.1513e-06, 4.3635e-09])
		#ss = np.array([-216.63, 0, -0.00018466, 4.7064e-06, -5.0066e-09])

		RR = np.zeros((3, 60))
		with open('C:\william\FINALRRFIN_ml.txt') as rrf:
			i = 0
			for line in rrf:
				RR[i] = line.split()
				i+=1

		RRfin = np.zeros((20, 3, 3))

		img = 0
		for i in range(0, len(RR[0]), 3):
			RRfin[img][0][0] = RR[0][i]
			RRfin[img][0][1] = RR[0][i+1]
			RRfin[img][0][2] = RR[0][i+2]
			RRfin[img][1][0] = RR[1][i]
			RRfin[img][1][1] = RR[1][i+1]
			RRfin[img][1][2] = RR[1][i+2]
			RRfin[img][2][0] = RR[2][i]
			RRfin[img][2][1] = RR[2][i+1]
			RRfin[img][2][2] = RR[2][i+2]
			img+=1

		return RRfin, ss

	def getMLXYReproj(self, i):

		XpProject = []
		YpProject = []

		with open('C:\william\Xp_reprojected' + str(i+1) + '_ml.txt') as prj:
			for line in prj:
				XpProject = line.split()

		with open('C:\william\Yp_reprojected' + str(i+1) + '_ml.txt') as prj:
			for line in prj:
				YpProject = line.split()


		return np.array(XpProject).astype('float'), np.array(YpProject).astype('float')

	def getPointsH5(self):
		#Use this to read in .h5 chessboard points. Used to have exact same points testable in Matlab and Python, since matlab and OCV finds slightly different corners

		h5f = h5py.File('C:\william\Spherical\Scaramuzza_OCamCalib_v3.0_win\Scaramuzza_OCamCalib_v3.0_win\\backsideChessboardPts.h5', 'r')
		readInObj = h5f['obj'][:]
		readInImg = h5f['img'][:]
		h5f.close()

		imgAbs = np.copy(readInImg)

		yc = 540  # TODO: pull from images?, correct way round? Even needed?, Ugh, set to opposite what's in calibSphere?
		xc = 480
		print 'yc: ', yc, ' xc: ', xc
		for imgi in range(len(readInImg)):
			for pti in range(len(readInImg[imgi])):
				tmp = readInImg[imgi][pti][0] #swap around
				readInImg[imgi][pti][0] = readInImg[imgi][pti][1]
				readInImg[imgi][pti][1] = tmp
				readInImg[imgi][pti][0] -= yc #subtract centre
				readInImg[imgi][pti][1] -= xc

		return readInImg, readInObj, imgAbs #Note I've done the x, y swap when building XpAbs, YpAbs in init