##############################################################################
# Copyright (C) 2018, 2019, 2020 Dominic O'Kane
##############################################################################

import numpy as np

from ...finutils.FinDate import FinDate
from ...finutils.FinCalendar import FinCalendar
from ...finutils.FinCalendar import FinCalendarTypes
from ...finutils.FinCalendar import FinDateGenRuleTypes
from ...finutils.FinCalendar import FinBusDayAdjustTypes
from ...finutils.FinDayCount import FinDayCount, FinDayCountTypes
from ...finutils.FinFrequency import FinFrequencyTypes
from ...finutils.FinGlobalVariables import gDaysInYear
from ...finutils.FinMath import ONE_MILLION, N
from ...finutils.FinError import FinError
from ...finutils.FinSchedule import FinSchedule
from ...finutils.FinHelperFunctions import labelToString
from ...products.libor.FinLiborModelTypes import FinLiborModelBlack
from ...products.libor.FinLiborModelTypes import FinLiborModelShiftedBlack
from ...products.libor.FinLiborModelTypes import FinLiborModelSABR
from ...models.FinModelSABR import blackVolFromSABR

##########################################################################

from enum import Enum


class FinLiborCapFloorType(Enum):
    CAP = 1
    FLOOR = 2


class FinLiborCapFloorModelTypes(Enum):
    BLACK = 1
    SHIFTED_BLACK = 2
    SABR = 3

##########################################################################


class FinLiborCapFloor():

    def __init__(self,
                 startDate,
                 maturityDateOrTenor,
                 optionType,
                 strikeRate,
                 lastFixing=None,
                 frequencyType=FinFrequencyTypes.QUARTERLY,
                 dayCountType=FinDayCountTypes.THIRTY_E_360_ISDA,
                 notional=ONE_MILLION,
                 calendarType=FinCalendarTypes.WEEKEND,
                 busDayAdjustType=FinBusDayAdjustTypes.FOLLOWING,
                 dateGenRuleType=FinDateGenRuleTypes.BACKWARD):

        if type(startDate) != FinDate:
            raise ValueError("Start date must be a FinDate.")

        if calendarType not in FinCalendarTypes:
            raise ValueError("Unknown Calendar type " + str(calendarType))

        self._calendarType = calendarType

        if busDayAdjustType not in FinBusDayAdjustTypes:
            raise ValueError("Unknown Business Day Adjust type " +
                             str(busDayAdjustType))

        self._busDayAdjustType = busDayAdjustType

        if type(maturityDateOrTenor) == FinDate:
            maturityDate = maturityDateOrTenor
        else:
            maturityDate = startDate.addTenor(maturityDateOrTenor)
            calendar = FinCalendar(self._calendarType)
            maturityDate = calendar.adjust(maturityDate,
                                           self._busDayAdjustType)

        if startDate > maturityDate:
            raise FinError("Start date must be before maturity date")

        if optionType not in FinLiborCapFloorType:
            raise FinError("Unknown Libor Cap Floor type " + str(optionType))

        if dayCountType not in FinDayCountTypes:
            raise FinError(
                "Unknown Cap Floor DayCountRule type " +
                str(dayCountType))

        if frequencyType not in FinFrequencyTypes:
            raise FinError(
                "Unknown CapFloor Frequency type " +
                str(frequencyType))

        if calendarType not in FinCalendarTypes:
            raise FinError("Unknown Calendar type " + str(calendarType))

        if busDayAdjustType not in FinBusDayAdjustTypes:
            raise FinError(
                "Unknown Business Day Adjust type " +
                str(busDayAdjustType))

        if dateGenRuleType not in FinDateGenRuleTypes:
            raise FinError(
                "Unknown Date Gen Rule type " +
                str(dateGenRuleType))

        self._startDate = startDate
        self._maturityDate = maturityDate
        self._optionType = optionType
        self._strikeRate = strikeRate
        self._lastFixing = lastFixing
        self._frequencyType = frequencyType
        self._dayCountType = dayCountType
        self._notional = notional
        self._dateGenRuleType = dateGenRuleType

        self._capFloorLetValues = []
        self._capFloorLetAlphas = []
        self._capFloorLetFwdRates = []
        self._capFloorLetIntrinsic = []
        self._capFloorLetDiscountFactors = []
        self._capFloorPV = []

        self._valuationDate = None

##########################################################################

    def value(self,
              valuationDate,
              liborCurve,
              model):

        self._valuationDate = valuationDate

        self._capFloorDates = FinSchedule(self._startDate,
                                          self._maturityDate,
                                          self._frequencyType,
                                          self._calendarType,
                                          self._busDayAdjustType,
                                          self._dateGenRuleType).generate()

        dayCounter = FinDayCount(self._dayCountType)
        numOptions = len(self._capFloorDates)
        strikeRate = self._strikeRate

        if strikeRate < 0.0:
            raise FinError("Strike < 0.0")

        if numOptions <= 1:
            raise FinError("Number of options in capfloor equals 1")

        #######################################################################

        self._capFloorLetValues = [0]
        self._capFloorLetAlphas = [0]
        self._capFloorLetFwdRates = [0]
        self._capFloorLetIntrinsic = [0]
        self._capFloorLetDiscountFactors = [1.00]
        self._capFloorPV = [0.0]

        #######################################################################

        capFloorValue = 0.0
        capFloorLetValue = 0.0
        # Value the first caplet or floorlet with known payoff

        startDate = self._startDate
        endDate = self._capFloorDates[1]

        if self._lastFixing is None:
            fwdRate = liborCurve.fwdRate(startDate, endDate,
                                         self._dayCountType)
        else:
            fwdRate = self._lastFixing

        alpha = dayCounter.yearFrac(startDate, endDate)
        df = liborCurve.df(endDate)

        if self._optionType == FinLiborCapFloorType.CAP:
            capFloorLetValue = df * alpha * max(fwdRate - strikeRate, 0)
        elif self._optionType == FinLiborCapFloorType.FLOOR:
            capFloorLetValue = df * alpha * max(strikeRate - fwdRate, 0)

        capFloorLetValue *= self._notional
        capFloorValue += capFloorLetValue

        self._capFloorLetFwdRates.append(fwdRate)
        self._capFloorLetValues.append(capFloorLetValue)
        self._capFloorLetAlphas.append(alpha)
        self._capFloorLetIntrinsic.append(capFloorLetValue)
        self._capFloorLetDiscountFactors.append(df)
        self._capFloorPV.append(capFloorValue)

        for i in range(2, numOptions):

            startDate = self._capFloorDates[i - 1]
            endDate = self._capFloorDates[i]
            alpha = dayCounter.yearFrac(startDate, endDate)
            df = liborCurve.df(endDate)
            fwdRate = liborCurve.fwdRate(startDate, endDate,
                                         self._dayCountType)

            if self._optionType == FinLiborCapFloorType.CAP:
                intrinsicValue = df * alpha * max(fwdRate - strikeRate, 0)
            elif self._optionType == FinLiborCapFloorType.FLOOR:
                intrinsicValue = df * alpha * max(strikeRate - fwdRate, 0)

            intrinsicValue *= self._notional

            capFloorLetValue = self.valueCapletFloorLet(valuationDate,
                                                        startDate,
                                                        endDate,
                                                        liborCurve,
                                                        model)

            capFloorLetValue *= self._notional * alpha
            capFloorValue += capFloorLetValue

            self._capFloorLetFwdRates.append(fwdRate)
            self._capFloorLetValues.append(capFloorLetValue)
            self._capFloorLetAlphas.append(alpha)
            self._capFloorLetIntrinsic.append(intrinsicValue)
            self._capFloorLetDiscountFactors.append(df)
            self._capFloorPV.append(capFloorValue)

        return capFloorValue

##########################################################################

    def valueCapletFloorLet(self,
                            valuationDate,
                            startDate,
                            endDate,
                            liborCurve,
                            model):

        df = liborCurve.df(endDate)
        t = (startDate - valuationDate) / gDaysInYear
        f = liborCurve.fwdRate(startDate, endDate, self._dayCountType)
        k = self._strikeRate

        if k == 0.0:
            k = 1e-10

        if type(model) == FinLiborModelBlack:

            v = model._volatility

            if v < 0:
                raise FinError("Black Volatility must be positive")

            if v == 0.0:
                v = 1e-10

            if f <= 0:
                raise FinError("Forward must be positive in lognormal model.")

            d1 = (np.log(f / k) + v * v * t / 2.0) / v / np.sqrt(t)
            d2 = d1 - v * np.sqrt(t)

            if self._optionType == FinLiborCapFloorType.CAP:
                capFloorLetValue = df * (f * N(+d1) - k * N(+d2))
            elif self._optionType == FinLiborCapFloorType.FLOOR:
                capFloorLetValue = df * (k * N(-d2) - f * N(-d1))

        elif type(model) == FinLiborModelShiftedBlack:

            v = model._volatility
            h = model._shift

            if v <= 0:
                raise FinError("Black Volatility must be positive")

            d1 = (np.log((f - h) / (k - h)) + v * v * t / 2.0) / v / np.sqrt(t)
            d2 = d1 - v * np.sqrt(t)

            if self._optionType == FinLiborCapFloorType.CAP:
                capFloorLetValue = df * ((f - h) * N(+d1) - (k - h) * N(+d2))
            elif self._optionType == FinLiborCapFloorType.FLOOR:
                capFloorLetValue = df * ((k - h) * N(-d2) - (f - h) * N(-d1))

        elif type(model) == FinLiborModelSABR:

            alpha = model._alpha
            beta = model._beta
            rho = model._rho
            nu = model._nu

            v = blackVolFromSABR(alpha, beta, rho, nu, f, k, t)

            d1 = (np.log((f) / (k)) + v * v * t / 2.0) / v / np.sqrt(t)
            d2 = d1 - v * np.sqrt(t)

            if self._optionType == FinLiborCapFloorType.CAP:
                capFloorLetValue = df * ((f) * N(+d1) - (k) * N(+d2))
            elif self._optionType == FinLiborCapFloorType.FLOOR:
                capFloorLetValue = df * ((k) * N(-d2) - (f) * N(-d1))

        else:
            raise FinError("Unknown model type " + str(model))

        return capFloorLetValue

###############################################################################

    def printLeg(self):
        ''' Prints the cap floor amounts. '''

        print("START DATE:", self._startDate)
        print("MATURITY DATE:", self._maturityDate)
        print("OPTION TYPE", str(self._optionType))
        print("STRIKE (%):", self._strikeRate * 100)
        print("FREQUENCY:", str(self._frequencyType))
        print("DAY COUNT:", str(self._dayCountType))
        print("VALUATION DATE", self._valuationDate)

        if len(self._capFloorLetValues) == 0:
            print("Caplets not calculated.")
            return

        if self._optionType == FinLiborCapFloorType.CAP:
            header = "PAYMENT_DATE     YEAR_FRAC   FWD_RATE    INTRINSIC      "
            header += "     DF    CAPLET_PV       CUM_PV"
        elif self._optionType == FinLiborCapFloorType.FLOOR:
            header = "PAYMENT_DATE     YEAR_FRAC   FWD_RATE    INTRINSIC      "
            header += "     DF    FLRLET_PV       CUM_PV"

        print(header)

        iFlow = 0

        for paymentDate in self._capFloorDates:
            print("%15s %10.7f  %9.5f %12.2f %12.6f %12.2f %12.2f" %
                  (paymentDate,
                   self._capFloorLetAlphas[iFlow],
                   self._capFloorLetFwdRates[iFlow]*100,
                   self._capFloorLetIntrinsic[iFlow],
                   self._capFloorLetDiscountFactors[iFlow],
                   self._capFloorLetValues[iFlow],
                   self._capFloorPV[iFlow]))

            iFlow += 1

###############################################################################

    def __repr__(self):
        s = labelToString("START DATE", self._startDate)
        s += labelToString("MATURITY DATE", self._maturityDate)
        s += labelToString("STRIKE COUPON", self._strikeRate * 100)
        s += labelToString("OPTION TYPE", str(self._optionType))
        s += labelToString("FREQUENCY", str(self._frequencyType))
        s += labelToString("DAY COUNT", str(self._dayCountType), "")
        return s

###############################################################################

    def print(self):
        print(self)

###############################################################################
