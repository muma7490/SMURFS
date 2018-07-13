import numpy as np
from astropy.stats import LombScargle
from scipy.optimize import curve_fit
from typing import Tuple, List

from smurfs.files import saveAmpSpectrumAndImage
from smurfs.support import *


@timeit
def calculateAmplitudeSpectrum(data: np.ndarray, frequencyBoundary: Tuple[float, float] = (0, 50)) -> np.ndarray:
    """
    This function computes a periodogram using the LombScargle algorithm. There are different implementations available
    and we leave it up to astropy to decide which one should be applied
    :param data: Temporal dataset, an observation by some kind instrument. First axis time, second axis flux
    :param frequencyBoundary: Boundary that should be considered when computing the spectrum
    :return: 2-D Array, containing frequency (first array) and amplitude (second array)
    """
    if frequencyBoundary[0] > frequencyBoundary[1]:
        raise ValueError(b"f_min has to be smaller than f_max!")

    # create object
    ls = LombScargle(data[0], data[1], normalization='psd')

    # if defined max frequency is bigger than the nyquist frequency, cutoff at nyquist
    nFrequency = nyquistFrequency(data)
    if frequencyBoundary[1] > nFrequency:
        print(term.format("Upper windowsize of {0} is higher than Nyquist frequency, using Nyquist at {1}"
                          .format(frequencyBoundary[1], nyquistFrequency),term.Color.RED))
        max_frequency = nFrequency
    else:
        max_frequency = frequencyBoundary[1]

    # compute Spectrum
    f, p = ls.autopower(minimum_frequency=frequencyBoundary[0], maximum_frequency=max_frequency, samples_per_peak=100)

    # normalization of psd in order to get good amplitudes
    p = np.sqrt(4 / len(data[0])) * np.sqrt(p)

    # removing first item
    p = p[1:]
    f = f[1:]

    # restricting values to upper boundary
    p = p[f < frequencyBoundary[1]]
    f = f[f < frequencyBoundary[1]]

    return np.array((f, p))


@timeit
def nyquistFrequency(data: np.ndarray) -> float:
    """
    Computes Nyquist frequency.
    :param data: Dataset, in time domain.
    :return: Nyquist frequency of dataset
    """
    return float(1 / (2 * findMostCommonDiff(data[0])))


def findMostCommonDiff(time: np.ndarray) -> float:
    """
    Finds the most common time difference between two data points.
    :param time:
    :return:
    """
    realDiffX = time[1:len(time)] - time[0:len(time) - 1]
    (values, counts) = np.unique(realDiffX, return_counts=True)
    mostCommon = values[np.argmax(counts)]
    return mostCommon


def findMaxPowerFrequency(ampSpectrum: np.ndarray):
    maxY = max(ampSpectrum[1])
    maxX = ampSpectrum[0][abs(ampSpectrum[1] - max(ampSpectrum[1])) < 10 ** -4][0]

    return maxY, maxX


def findAndRemoveMaxFrequency(lightCurve: np.ndarray, ampSpectrum: np.ndarray) -> Tuple[List[float], np.ndarray]:
    """
    Finds the frequency with maximum power in the spectrum, fits it to the dataset and than removes this frequency
    from the initial dataset.
    :param lightCurve: Lightcurve dataset. This is the data where the fit is applied to, and its removed version is
    returned
    :param ampSpectrum: Amplitude spectrum of lightCurve. Should be computed with the same dataset that is provided here
    :return: Fit parameters, Reduced lightcurve
    """
    maxY, maxX = findMaxPowerFrequency(ampSpectrum)
    popt = [-1, -1, -1]
    arr = [maxY, maxX, 0]

    # First fit could provide negative values for amplitude and frequency if the phase is moved by pi. Therefore run
    # again, with phase moved by pi as long as we don't have positive values for freuqency and amplitude
    while popt[0] < 0 or popt[1] < 0:
        try:
            popt, pcov = curve_fit(sin, lightCurve[0], lightCurve[1], p0=arr)
        except RuntimeError:
            print(term.format("Failed to find a good fit for Frequency " + str(maxX) + "c/d", term.Color.RED))
            raise RuntimeError

        # if amp < 0 -> move sin to plus using the phase by adding pi
        if popt[0] < 0 or popt[1] < 0:
            popt[0] = abs(popt[0])
            popt[1] = abs(popt[1])
            popt[2] += -np.pi if popt[2] > np.pi else np.pi
        arr = popt

        retLightCurve = np.array((lightCurve[0], lightCurve[1] - sin(lightCurve[0], *popt)))

    return popt, retLightCurve


@timeit
def computeSignalToNoise(ampSpectrum: np.ndarray, windowSize: float) -> float:
    """
    Computes signal to noise ratio at frequency f.
    :param ampSpectrum:
    :param windowSize:
    :return:
    """
    y = ampSpectrum[1]
    x = ampSpectrum[0]

    # find minimas adjacent to maxima of y
    lowerMinima, upperMinima = findNextMinimas(y)
    singleStep = np.mean(np.diff(x))
    length_half = int(windowSize / singleStep)

    data = np.append(y[lowerMinima - length_half:lowerMinima], y[upperMinima:upperMinima + length_half])
    meanValue = np.mean(data)
    maxVal = y[abs(y - max(y)) < 10 ** -6][0]

    return float(maxVal / meanValue)


@timeit
def findNextMinimas(yData: np.ndarray) -> Tuple[int, int]:
    index = int(np.where(abs(yData - max(yData)) < 10 ** -6)[0][0])
    minimaFound = False
    counter = 1
    lowerMinima = -1
    upperMinima = -1
    while (minimaFound == False):
        negCounter = index - counter
        posCounter = index + counter
        if negCounter -1 < 0:
            lowerMinima = negCounter
        elif checkMinima(yData, negCounter):
            lowerMinima = negCounter

        if posCounter + 1 >= len(yData):
            upperMinima = posCounter
        elif checkMinima(yData, posCounter):
            upperMinima = posCounter

        if lowerMinima != -1 and upperMinima != -1:
            minimaFound = True
        counter += 1

    return lowerMinima, upperMinima


def checkMinima(yData: np.ndarray, counter: int) -> bool:
    return yData[counter] < yData[counter + 1] and yData[counter] < yData[counter - 1]


def sin(x: np.ndarray, amp: float, f: float, phase: float) -> np.ndarray:
    return amp * np.sin(2 * np.pi * f * x + phase)


def cutoffCriterion(frequencyList: List):
    if len(frequencyList) < similarFrequenciesCount:
        return True

    lastFrequencies = np.array(frequencyList[-similarFrequenciesCount:])
    stdDev = lastFrequencies.std()
    if stdDev < similarityStdDev:
        print(
            term.format("The last " + str(similarFrequenciesCount) + " where to similar, with a standard deviation of "
                        + str(stdDev) + ". Stopping analysis for this set", term.Color.RED))
        return False
    else:
        return True


def prepareSpectrogram(spectrum: np.ndarray, timerange: Tuple[int, int]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    t = np.linspace(timerange[0], timerange[1],num=5)
    f = spectrum[0]
    i = spectrum[1]

    if defines.maxiLength is None:
        defines.maxiLength = len(i)
    elif defines.maxiLength > len(i):
        i = np.append(i, np.linspace(0, 0, num=defines.maxiLength - len(i)))
    else:
        i = i[0:defines.maxiLength]

    tmpSpectrum = i

    for j in range(0, len(t) - 1):
        i = np.vstack((i, tmpSpectrum))

    return f, t, i


def recursiveFrequencyFinder(data: np.ndarray, snrCriterion: float, windowSize: float, path: str = "",
                             **kwargs):
    """
    Recursively finds all significant frequencies of a given dataset. Takes a lightcurve, transforms it
    using the lomb scargle algorithm, finds the frequency with highest power, fits the frequency to the
    dataset and subtracts it from the dataset. Also prepares the result for the spectrogram plotted at the
    end of the dataset.
    :param data: Input data. Represents a lightcurve. Requires a two dimensional array, with the first
    dimension being the temporal axis, and the second the intensity.
    :param snrCriterion: Cutoff criterion that defines significancy. The code computes the signal to noise
    ratio after each subtraction of the fitted data and checks if the given SNR is bigger than the calculated
    SNR. If this is the case, the algorithm stops.
    :param windowSize: The windowsize of the spectrum. There are also sanity checks going on here, if the
    maximum frequency is higher than the nyquist frequency than the nyquist frequency is used.
    :param path: Path to save stuff to.
    :param kwargs: Commandline parameters.
    :return: List of significant frequencies, initial spectrum, time array, intensity matrix (for spectrogram)
    """
    frequencyList = None
    f, t, i = None, None, None
    try:
        snr = 100
        frequencyList = []
        print(term.format("List of frequencys, amplitudes, phases, S/N", term.Color.CYAN))
        savePath = path + "results/{0:0=3d}".format(int(data[0][0]))
        savePath += "_{0:0=3d}/".format(int(max(data[0])))

        while (snr > snrCriterion):
            try:
                frequencyList.append((fit[1], snr, fit[0], fit[2],))
                saveStuff = True if kwargs['mode'] == 'Full' else False
            except:
                saveStuff = True
            amp = calculateAmplitudeSpectrum(data, kwargs['frequencyRange'])
            snr = computeSignalToNoise(amp, windowSize)
            fit, data = findAndRemoveMaxFrequency(data, amp)

            print(term.format(str(fit[1]) + "c/d     " + str(fit[0]) + "     " + str(fit[2]) + "    " + str(snr),
                              term.Color.CYAN))

            fileNames = "amplitude_spectrum_f_" + str(len(frequencyList))

            if saveStuff:
                saveAmpSpectrumAndImage(amp, savePath, fileNames)
                f, t, i = prepareSpectrogram(amp, (int(data[0][0]), int(np.max(data[0]))))

            if not cutoffCriterion(frequencyList):
                break

        try:
            if kwargs['mode'] == 'Normal':
                pass
                saveAmpSpectrumAndImage(amp, savePath, fileNames)
        except KeyError:
            pass
    except KeyboardInterrupt:
        print(term.format("Interrupted Run", term.Color.RED))
        defines.dieGracefully = True
        return frequencyList, f, t, i

    return frequencyList, f, t, i


def combineDatasets(fList: List[np.ndarray], tList: List[np.ndarray], iList: List[np.ndarray]) -> Tuple[
    np.ndarray, np.ndarray, np.ndarray]:
    if fList == [] or tList == [] or iList == []:
        raise ValueError(term.format("Size of all result lists must be equal!",term.Color.RED))

    f = fList[0]

    for i in tList:
        try:
            t = np.hstack((t,i))
        except UnboundLocalError:
            t = i

    for j in iList:
        try:
            intensity = np.row_stack((intensity,j))
        except UnboundLocalError:
            intensity = j

    return f,t,intensity