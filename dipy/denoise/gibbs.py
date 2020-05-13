
import numpy as np

try:
    # SciPy 1.4+ has a more efficient FFT under scipy.fft
    from scipy.fft import fft2, ifft2, fftshift, ifftshift
except ImportError:
    from scipy.fftpack import fft2, ifft2, fftshift, ifftshift


def _image_tv(x, axis=0, n_points=3):
    """ Computes total variation (TV) of matrix x across a given axis and
    along two directions.

    Parameters
    ----------
    x : 2D ndarray
        matrix x
    axis : int (0 or 1)
        Axis which TV will be calculated. Default a is set to 0.
    n_points : int
        Number of points to be included in TV calculation.

    Returns
    -------
    ptv : 2D ndarray
        Total variation calculated from the right neighbours of each point.
    ntv : 2D ndarray
        Total variation calculated from the left neighbours of each point.

    """
    if axis:
        xs = x
    else:
        xs = x.transpose((1, 0) + tuple(range(2, x.ndim)))

    # Add copies of the data so that data extreme points are also analysed
    xs = np.concatenate((xs[:, (-n_points-1):, ...], xs, xs[:, 0:(n_points+1), ...]),
                        axis=1)

    ptv = np.abs(
        xs[:, (n_points + 1) : (-n_points - 1), ...]
        - xs[:, (n_points + 2) : (-n_points), ...]
    )
    ntv = np.abs(
        xs[:, (n_points + 1) : (-n_points - 1), ...]
        - xs[:, (n_points) : (-n_points - 2), ...]
    )

    for n in range(1, n_points):
        ptv += np.abs(
            xs[:, (n_points + 1 + n) : (-n_points - 1 + n), ...]
            - xs[:, (n_points + 2 + n) : (-n_points + n), ...]
        )
        ntv += np.abs(
            xs[:, (n_points + 1 - n) : (-n_points - 1 - n), ...]
            - xs[:, (n_points - n) : (-n_points - 2 - n), ...]
        )

    if not axis:
        ptv = ptv.transpose((1, 0) + tuple(range(2, x.ndim)))
        ntv = ntv.transpose((1, 0) + tuple(range(2, x.ndim)))
    return ptv, ntv



def _gibbs_removal_1d(x, axis=0, n_points=3):
    """Suppresses Gibbs ringing along a given axis using fourier sub-shifts.

    Parameters
    ----------
    x : 2D ndarray
        Matrix x.
    axis : int (0 or 1)
        Axis in which Gibbs oscillations will be suppressed.
        Default is set to 0.
    n_points : int, optional
        Number of neighbours to access local TV (see note).
        Default is set to 3.

    Returns
    -------
    xc : 2D ndarray
        Matrix with suppressed Gibbs oscillations along the given axis.

    Notes
    -----
    This function suppresses the effects of Gibbs oscillations based on the
    analysis of local total variation (TV). Although artefact correction is
    done based on two adjacent points for each voxel, total variation should be
    accessed in a larger range of neighbours. The number of neighbours to be
    considered in TV calculation can be adjusted using the parameter n_points.

    """
    float_dtype = np.promote_types(x.dtype, np.float32)

    ssamp = np.linspace(0.02, 0.9, num=45, dtype=float_dtype)

    if axis:
        xs = x.copy()
    else:
        xs = x.transpose((1, 0) + tuple(range(2, x.ndim))).copy()

    # TV for shift zero (baseline)
    tvr, tvl = _image_tv(xs, axis=1, n_points=n_points)
    tvp = np.minimum(tvr, tvl)
    tvn = tvp.copy()

    # Find optimal shift for gibbs removal
    isp = xs.copy()
    isn = xs.copy()
    sp = np.zeros(xs.shape, dtype=float_dtype)
    sn = np.zeros(xs.shape, dtype=float_dtype)
    N = xs.shape[1]
    c = fft2(xs, axes=(0, 1))
    c = fftshift(c, axes=(0, 1))
    k = np.linspace(-N/2, N/2-1, num=N, dtype=float_dtype)
    k = (2.0j * np.pi * k) / N
    if xs.ndim == 2:
        k = k[np.newaxis, :]
    elif xs.ndim == 3:
        k = k[np.newaxis, :, np.newaxis]
    for s in ssamp:
        # Access positive shift for given s
        ks = k * s
        eks = np.exp(ks)
        img_p = c * eks
        img_p = fftshift(img_p, axes=(0, 1))
        img_p = ifft2(img_p, axes=(0, 1))
        img_p = np.abs(img_p)
        tvsr, tvsl = _image_tv(img_p, axis=1, n_points=n_points)
        tvs_p = np.minimum(tvsr, tvsl)

        # Access negative shift for given s
        img_n = c * np.conj(eks)
        img_n = fftshift(img_n, axes=(0, 1))
        img_n = ifft2(img_n, axes=(0, 1))
        img_n = np.abs(img_n)
        tvsr, tvsl = _image_tv(img_n, axis=1, n_points=n_points)
        tvs_n = np.minimum(tvsr, tvsl)

        maskp = tvp > tvs_p
        maskn = tvn > tvs_n

        # Update positive shift params
        isp[maskp] = img_p[maskp]
        sp[maskp] = s
        tvp[maskp] = tvs_p[maskp]

        # Update negative shift params
        isn[maskn] = img_n[maskn]
        sn[maskn] = s
        tvn[maskn] = tvs_n[maskn]

    # check non-zero sub-voxel shifts
    idx = np.nonzero(sp + sn)

    # use positive and negative optimal sub-voxel shifts to interpolate to
    # original grid points
    sn_i = sn[idx]
    isn_i = isn[idx]
    tmp = isp[idx] - isn_i
    tmp /= sp[idx] + sn_i
    tmp *= sn_i
    tmp += isn_i
    xs[idx] = tmp

    if not axis:
        xs = xs.transpose((1, 0) + tuple(range(2, xs.ndim)))
    return xs


def _weights(shape, image_dtype):
    """ Computes the weights necessary to combine two images processed by
    the 1D Gibbs removal procedure along two different axes [1]_.

    Parameters
    ----------
    shape : tuple
        shape of the image.

    Returns
    -------
    G0 : 2D ndarray
        Weights for the image corrected along axis 0.
    G1 : 2D ndarray
        Weights for the image corrected along axis 1.

    References
    ----------
    .. [1] Kellner E, Dhital B, Kiselev VG, Reisert M. Gibbs-ringing artifact
           removal based on local subvoxel-shifts. Magn Reson Med. 2016
           doi: 10.1002/mrm.26054.

    """

    dtype = np.promote_types(np.float32, image_dtype)

    G0 = np.zeros(shape, dtype=dtype)
    G1 = np.zeros(shape, dtype=dtype)
    k0 = np.linspace(-np.pi, np.pi, num=shape[0], dtype=dtype)
    k1 = np.linspace(-np.pi, np.pi, num=shape[1], dtype=dtype)

    # Middle points
    K1, K0 = np.meshgrid(k1[1:-1], k0[1:-1])
    cosk0 = 1.0 + np.cos(K0)
    cosk1 = 1.0 + np.cos(K1)
    G1[1:-1, 1:-1] = cosk0 / (cosk0 + cosk1)
    G0[1:-1, 1:-1] = cosk1 / (cosk0 + cosk1)

    # Boundaries
    G1[1:-1, 0] = G1[1:-1, -1] = 1
    G1[0, 0] = G1[-1, -1] = G1[0, -1] = G1[-1, 0] = 1/2
    G0[0, 1:-1] = G0[-1, 1:-1] = 1
    G0[0, 0] = G0[-1, -1] = G0[0, -1] = G0[-1, 0] = 1/2

    return G0, G1


def _gibbs_removal_2d(image, n_points=3, G0=None, G1=None):
    """ Suppress Gibbs ringing of a 2D image.

    Parameters
    ----------
    image : 2D ndarray
        Matrix containing the 2D image.
    n_points : int, optional
        Number of neighbours to access local TV (see note). Default is
        set to 3.
    G0 : 2D ndarray, optional.
        Weights for the image corrected along axis 0. If not given, the
        function estimates them using the function :func:`_weights`.
    G1 : 2D ndarray
        Weights for the image corrected along axis 1. If not given, the
        function estimates them using the function :func:`_weights`.

    Returns
    -------
    imagec : 2D ndarray
        Matrix with Gibbs oscillations reduced along axis a.

    Notes
    -----
    This function suppresses the effects of Gibbs oscillations based on the
    analysis of local total variation (TV). Although artefact correction is
    done based on two adjacent points for each voxel, total variation should be
    accessed in a larger range of neighbours. The number of neighbours to be
    considered in TV calculation can be adjusted using the parameter n_points.

    References
    ----------
    Please cite the following articles
    .. [1] Neto Henriques, R., 2018. Advanced Methods for Diffusion MRI Data
           Analysis and their Application to the Healthy Ageing Brain
           (Doctoral thesis). https://doi.org/10.17863/CAM.29356
    .. [2] Kellner E, Dhital B, Kiselev VG, Reisert M. Gibbs-ringing artifact
           removal based on local subvoxel-shifts. Magn Reson Med. 2016
           doi: 10.1002/mrm.26054.

    """
    if G0 is None or G1 is None:
        G0, G1 = _weights(image.shape[:2], image.dtype)
        if image.ndim > 2:
            G0 = G0[..., np.newaxis]
            G1 = G1[..., np.newaxis]

    if image.ndim not in [2, 3]:
        raise ValueError(
            "expected a 2D image or a 3D array corresponding to a batch of 2D "
            "images stacked along the last axis"
        )
    img_c1 = _gibbs_removal_1d(image, axis=1, n_points=n_points)
    img_c0 = _gibbs_removal_1d(image, axis=0, n_points=n_points)

    C1 = fft2(img_c1, axes=(0, 1))
    C0 = fft2(img_c0, axes=(0, 1))
    imagec = fftshift(C1, axes=(0, 1)) * G1
    imagec += fftshift(C0, axes=(0, 1)) * G0
    imagec = ifft2(imagec, axes=(0, 1))
    np.abs(imagec, out=imagec)

    return imagec


def gibbs_removal(vol, slice_axis=2, n_points=3):
    """Suppresses Gibbs ringing artefacts of images volumes.

    Parameters
    ----------
    vol : ndarray ([X, Y]), ([X, Y, Z]) or ([X, Y, Z, g])
        Matrix containing one volume (3D) or multiple (4D) volumes of images.
    slice_axis : int (0, 1, or 2)
        Data axis corresponding to the number of acquired slices.
        Default is set to the third axis.
    n_points : int, optional
        Number of neighbour points to access local TV (see note).
        Default is set to 3.

    Returns
    -------
    vol : ndarray ([X, Y]), ([X, Y, Z]) or ([X, Y, Z, g])
        Matrix containing one volume (3D) or multiple (4D) volumes of corrected
        images.

    Notes
    -----
    For 4D matrix last element should always correspond to the number of
    diffusion gradient directions.

    References
    ----------
    Please cite the following articles
    .. [1] Neto Henriques, R., 2018. Advanced Methods for Diffusion MRI Data
           Analysis and their Application to the Healthy Ageing Brain
           (Doctoral thesis). https://doi.org/10.17863/CAM.29356
    .. [2] Kellner E, Dhital B, Kiselev VG, Reisert M. Gibbs-ringing artifact
           removal based on local subvoxel-shifts. Magn Reson Med. 2016
           doi: 10.1002/mrm.26054.

    """
    nd = vol.ndim

    # check the axis corresponding to different slices
    # 1) This axis cannot be larger than 2
    if slice_axis > 2:
        raise ValueError("Different slices have to be organized along" +
                         "one of the 3 first matrix dimensions")

    # 2) If this is not 2, swap axes so that different slices are ordered
    # along axis 2. Note that swapping is not required if data is already a
    # single image
    elif slice_axis < 2 and nd > 2:
        vol = np.swapaxes(vol, slice_axis, 2)

    # check matrix dimension
    if nd == 4:
        inishap = vol.shape
        vol = vol.reshape((inishap[0], inishap[1], inishap[2] * inishap[3]))
    elif nd > 4:
        raise ValueError("Data have to be a 4D, 3D or 2D matrix")
    elif nd < 2:
        raise ValueError("Data is not an image")

    # Produce weigthing functions for 2D Gibbs removal
    shap = vol.shape
    G0, G1 = _weights(shap[:2], vol.dtype)

    # Run Gibbs removal of 2D images
    if nd > 2:
        G0 = G0[..., np.newaxis]
        G1 = G1[..., np.newaxis]
    vol = _gibbs_removal_2d(vol, n_points=n_points, G0=G0, G1=G1)

    # Reshape data to original format
    if nd == 4:
        vol = vol.reshape(inishap)
    if slice_axis < 2 and nd > 2:
        vol = np.swapaxes(vol, slice_axis, 2)

    return vol
