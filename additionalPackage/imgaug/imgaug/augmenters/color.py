"""
Augmenters that affect image colors or image colorspaces.

Do not import directly from this file, as the categorization is not final.
Use instead ::

    from imgaug import augmenters as iaa

and then e.g. ::

    seq = iaa.Sequential([
        iaa.Grayscale((0.0, 1.0)),
        iaa.AddToHueAndSaturation((-10, 10))
    ])

List of augmenters:

    * InColorspace (deprecated)
    * WithColorspace
    * WithHueAndSaturation
    * MultiplyHueAndSaturation
    * MultiplyHue
    * MultiplySaturation
    * AddToHueAndSaturation
    * AddToHue
    * AddToSaturation
    * ChangeColorspace
    * Grayscale
    * KMeansColorQuantization
    * UniformColorQuantization

"""
from __future__ import print_function, division, absolute_import

from abc import ABCMeta, abstractmethod

import numpy as np
import cv2
import six
import six.moves as sm

from . import meta
from . import blend
from . import arithmetic
import imgaug as ia
from .. import parameters as iap
from .. import dtypes as iadt
from .. import random as iarandom


CSPACE_RGB = "RGB"
CSPACE_BGR = "BGR"
CSPACE_GRAY = "GRAY"
CSPACE_YCrCb = "YCrCb"
CSPACE_HSV = "HSV"
CSPACE_HLS = "HLS"
CSPACE_Lab = "Lab"
# TODO add Luv to various color/contrast augmenters as random default choice?
CSPACE_Luv = "Luv"
CSPACE_YUV = "YUV"
CSPACE_CIE = "CIE"  # XYZ in OpenCV
CSPACE_ALL = {CSPACE_RGB, CSPACE_BGR, CSPACE_GRAY, CSPACE_YCrCb,
              CSPACE_HSV, CSPACE_HLS, CSPACE_Lab, CSPACE_Luv,
              CSPACE_YUV, CSPACE_CIE}


def _get_opencv_attr(attr_names):
    for attr_name in attr_names:
        if hasattr(cv2, attr_name):
            return getattr(cv2, attr_name)
    ia.warn("Could not find any of the following attributes in cv2: %s. "
            "This can cause issues with colorspace transformations." % (
                attr_names))
    return None


_CSPACE_OPENCV_CONV_VARS = {
    # RGB
    (CSPACE_RGB, CSPACE_BGR): cv2.COLOR_RGB2BGR,
    (CSPACE_RGB, CSPACE_GRAY): cv2.COLOR_RGB2GRAY,
    (CSPACE_RGB, CSPACE_YCrCb): _get_opencv_attr(["COLOR_RGB2YCR_CB"]),
    (CSPACE_RGB, CSPACE_HSV): cv2.COLOR_RGB2HSV,
    (CSPACE_RGB, CSPACE_HLS): cv2.COLOR_RGB2HLS,
    (CSPACE_RGB, CSPACE_Lab): _get_opencv_attr(["COLOR_RGB2LAB",
                                                "COLOR_RGB2Lab"]),
    (CSPACE_RGB, CSPACE_Luv): cv2.COLOR_RGB2LUV,
    (CSPACE_RGB, CSPACE_YUV): cv2.COLOR_RGB2YUV,
    (CSPACE_RGB, CSPACE_CIE): cv2.COLOR_RGB2XYZ,
    # BGR
    (CSPACE_BGR, CSPACE_RGB): cv2.COLOR_BGR2RGB,
    (CSPACE_BGR, CSPACE_GRAY): cv2.COLOR_BGR2GRAY,
    (CSPACE_BGR, CSPACE_YCrCb): _get_opencv_attr(["COLOR_BGR2YCR_CB"]),
    (CSPACE_BGR, CSPACE_HSV): cv2.COLOR_BGR2HSV,
    (CSPACE_BGR, CSPACE_HLS): cv2.COLOR_BGR2HLS,
    (CSPACE_BGR, CSPACE_Lab): _get_opencv_attr(["COLOR_BGR2LAB",
                                                "COLOR_BGR2Lab"]),
    (CSPACE_BGR, CSPACE_Luv): cv2.COLOR_BGR2LUV,
    (CSPACE_BGR, CSPACE_YUV): cv2.COLOR_BGR2YUV,
    (CSPACE_BGR, CSPACE_CIE): cv2.COLOR_BGR2XYZ,
    # GRAY
    # YCrCb
    (CSPACE_YCrCb, CSPACE_RGB): _get_opencv_attr(["COLOR_YCrCb2RGB",
                                                  "COLOR_YCR_CB2RGB"]),
    (CSPACE_YCrCb, CSPACE_BGR): _get_opencv_attr(["COLOR_YCrCb2BGR",
                                                  "COLOR_YCR_CB2BGR"]),
    # HSV
    (CSPACE_HSV, CSPACE_RGB): cv2.COLOR_HSV2RGB,
    (CSPACE_HSV, CSPACE_BGR): cv2.COLOR_HSV2BGR,
    # HLS
    (CSPACE_HLS, CSPACE_RGB): cv2.COLOR_HLS2RGB,
    (CSPACE_HLS, CSPACE_BGR): cv2.COLOR_HLS2BGR,
    # Lab
    (CSPACE_Lab, CSPACE_RGB): _get_opencv_attr(["COLOR_Lab2RGB",
                                                "COLOR_LAB2RGB"]),
    (CSPACE_Lab, CSPACE_BGR): _get_opencv_attr(["COLOR_Lab2BGR",
                                                "COLOR_LAB2BGR"]),
    # Luv
    (CSPACE_Luv, CSPACE_RGB): _get_opencv_attr(["COLOR_Luv2RGB",
                                                "COLOR_LUV2RGB"]),
    (CSPACE_Luv, CSPACE_BGR): _get_opencv_attr(["COLOR_Luv2BGR",
                                                "COLOR_LUV2BGR"]),
    # YUV
    (CSPACE_YUV, CSPACE_RGB): cv2.COLOR_YUV2RGB,
    (CSPACE_YUV, CSPACE_BGR): cv2.COLOR_YUV2BGR,
    # CIE
    (CSPACE_CIE, CSPACE_RGB): cv2.COLOR_XYZ2RGB,
    (CSPACE_CIE, CSPACE_BGR): cv2.COLOR_XYZ2BGR,
}

# This defines which colorspace pairs will be converted in-place in
# change_colorspace_(). Currently, all colorspaces seem to work fine with
# in-place transformations, which is why they are all set to True.
_CHANGE_COLORSPACE_INPLACE = {
    # RGB
    (CSPACE_RGB, CSPACE_BGR): True,
    (CSPACE_RGB, CSPACE_GRAY): True,
    (CSPACE_RGB, CSPACE_YCrCb): True,
    (CSPACE_RGB, CSPACE_HSV): True,
    (CSPACE_RGB, CSPACE_HLS): True,
    (CSPACE_RGB, CSPACE_Lab): True,
    (CSPACE_RGB, CSPACE_Luv): True,
    (CSPACE_RGB, CSPACE_YUV): True,
    (CSPACE_RGB, CSPACE_CIE): True,
    # BGR
    (CSPACE_BGR, CSPACE_RGB): True,
    (CSPACE_BGR, CSPACE_GRAY): True,
    (CSPACE_BGR, CSPACE_YCrCb): True,
    (CSPACE_BGR, CSPACE_HSV): True,
    (CSPACE_BGR, CSPACE_HLS): True,
    (CSPACE_BGR, CSPACE_Lab): True,
    (CSPACE_BGR, CSPACE_Luv): True,
    (CSPACE_BGR, CSPACE_YUV): True,
    (CSPACE_BGR, CSPACE_CIE): True,
    # GRAY
    # YCrCb
    (CSPACE_YCrCb, CSPACE_RGB): True,
    (CSPACE_YCrCb, CSPACE_BGR): True,
    # HSV
    (CSPACE_HSV, CSPACE_RGB): True,
    (CSPACE_HSV, CSPACE_BGR): True,
    # HLS
    (CSPACE_HLS, CSPACE_RGB): True,
    (CSPACE_HLS, CSPACE_BGR): True,
    # Lab
    (CSPACE_Lab, CSPACE_RGB): True,
    (CSPACE_Lab, CSPACE_BGR): True,
    # Luv
    (CSPACE_Luv, CSPACE_RGB): True,
    (CSPACE_Luv, CSPACE_BGR): True,
    # YUV
    (CSPACE_YUV, CSPACE_RGB): True,
    (CSPACE_YUV, CSPACE_BGR): True,
    # CIE
    (CSPACE_CIE, CSPACE_RGB): True,
    (CSPACE_CIE, CSPACE_BGR): True,
}


def change_colorspace_(image, to_colorspace, from_colorspace=CSPACE_RGB):
    """Change the colorspace of an image inplace.

    .. note ::

        All outputs of this function are `uint8`. For some colorspaces this
        may not be optimal.

    .. note ::

        Output grayscale images will still have three channels.

    dtype support::

        * ``uint8``: yes; fully tested
        * ``uint16``: no
        * ``uint32``: no
        * ``uint64``: no
        * ``int8``: no
        * ``int16``: no
        * ``int32``: no
        * ``int64``: no
        * ``float16``: no
        * ``float32``: no
        * ``float64``: no
        * ``float128``: no
        * ``bool``: no

    Parameters
    ----------
    image : ndarray
        The image to convert from one colorspace into another.
        Usually expected to have shape ``(H,W,3)``.

    to_colorspace : str
        The target colorspace. See the ``CSPACE`` constants,
        e.g. ``imgaug.augmenters.color.CSPACE_RGB``.

    from_colorspace : str, optional
        The source colorspace. Analogous to `to_colorspace`. Defaults
        to ``RGB``.

    Returns
    -------
    ndarray
        Image with target colorspace. *Can* be the same array instance as was
        originally provided (i.e. changed inplace). Grayscale images will
        still have three channels.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> import numpy as np
    >>> # fake RGB image
    >>> image_rgb = np.arange(4*4*3).astype(np.uint8).reshape((4, 4, 3))
    >>> image_bgr = iaa.change_colorspace_(np.copy(image_rgb), iaa.CSPACE_BGR)

    """
    # some colorspaces here should use image/255.0 according to
    # the docs, but at least for conversion to grayscale that
    # results in errors, ie uint8 is expected

    def _get_dst(image, from_to_cspace):
        if _CHANGE_COLORSPACE_INPLACE[from_to_cspace]:
            # inplace mode for cv2's cvtColor seems to have issues with
            # images that are views (e.g. image[..., 0:3]) and returns a
            # cv2.UMat instance instead of an array. So we check here first
            # if the array looks like it is non-contiguous or a view.
            if image.flags["C_CONTIGUOUS"]:
                return image
        return None

    iadt.gate_dtypes(
        image,
        allowed=["uint8"],
        disallowed=[
            "bool",
            "uint16", "uint32", "uint64", "uint128", "uint256",
            "int32", "int64", "int128", "int256",
            "float16", "float32", "float64", "float96", "float128",
            "float256"],
        augmenter=None)

    for arg_name in ["to_colorspace", "from_colorspace"]:
        assert locals()[arg_name] in CSPACE_ALL, (
            "Expected `%s` to be one of: %s. Got: %s." % (
                arg_name, CSPACE_ALL, locals()[arg_name]))

    assert from_colorspace != CSPACE_GRAY, (
        "Cannot convert from grayscale to another colorspace as colors "
        "cannot be recovered.")

    assert image.ndim == 3, (
        "Expected image shape to be three-dimensional, i.e. (H,W,C), "
        "got %d dimensions with shape %s." % (image.ndim, image.shape))
    assert image.shape[2] == 3, (
        "Expected number of channels to be three, got %d channels with "
        "shape %s." % (image.ndim, image.shape,))

    if from_colorspace == to_colorspace:
        return image

    from_to_direct = (from_colorspace, to_colorspace)
    from_to_indirect = [
        (from_colorspace, CSPACE_RGB),
        (CSPACE_RGB, to_colorspace)
    ]

    image_aug = image
    if from_to_direct in _CSPACE_OPENCV_CONV_VARS:
        from2to_var = _CSPACE_OPENCV_CONV_VARS[from_to_direct]
        dst = _get_dst(image_aug, from_to_direct)
        image_aug = cv2.cvtColor(image_aug, from2to_var, dst=dst)
    else:
        from2rgb_var = _CSPACE_OPENCV_CONV_VARS[from_to_indirect[0]]
        rgb2to_var = _CSPACE_OPENCV_CONV_VARS[from_to_indirect[1]]

        dst1 = _get_dst(image_aug, from_to_indirect[0])
        dst2 = _get_dst(image_aug, from_to_indirect[1])

        image_aug = cv2.cvtColor(image_aug, from2rgb_var, dst=dst1)
        image_aug = cv2.cvtColor(image_aug, rgb2to_var, dst=dst2)

    assert image_aug.dtype.name == "uint8"

    # for grayscale: covnert from (H, W) to (H, W, 3)
    if len(image_aug.shape) == 2:
        image_aug = image_aug[:, :, np.newaxis]
        image_aug = np.tile(image_aug, (1, 1, 3))

    return image_aug


def change_colorspaces_(images, to_colorspaces, from_colorspaces=CSPACE_RGB):
    """Change the colorspaces of a batch of images inplace.

    .. note ::

        All outputs of this function are `uint8`. For some colorspaces this
        may not be optimal.

    .. note ::

        Output grayscale images will still have three channels.

    dtype support::

        See :func:`imgaug.augmenters.color.change_colorspace_`.

    Parameters
    ----------
    images : ndarray or list of ndarray
        The images to convert from one colorspace into another.
        Either a list of ``(H,W,3)`` arrays or a single ``(N,H,W,3)`` array.

    to_colorspaces : str or list of str
        The target colorspaces. Either a single string (all images will be
        converted to the same colorspace) or a list of strings (one per image).
        See the ``CSPACE`` constants, e.g.
        ``imgaug.augmenters.color.CSPACE_RGB``.

    from_colorspaces : str or list of str, optional
        The source colorspace. Analogous to `to_colorspace`. Defaults
        to ``RGB``.

    Returns
    -------
    ndarray or list of ndarray
        Images with target colorspaces. *Can* contain the same array instances
        as were originally provided (i.e. changed inplace). Grayscale images
        will still have three channels.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> import numpy as np
    >>> # fake RGB image
    >>> image_rgb = np.arange(4*4*3).astype(np.uint8).reshape((4, 4, 3))
    >>> images_rgb = [image_rgb, image_rgb, image_rgb]
    >>> images_rgb_copy = [np.copy(image_rgb) for image_rgb in images_rgb]
    >>> images_bgr = iaa.change_colorspaces_(images_rgb_copy, iaa.CSPACE_BGR)

    Create three example ``RGB`` images and convert them to ``BGR`` colorspace.

    >>> images_rgb_copy = [np.copy(image_rgb) for image_rgb in images_rgb]
    >>> images_various = iaa.change_colorspaces_(
    >>>     images_rgb_copy, [iaa.CSPACE_BGR, iaa.CSPACE_HSV, iaa.CSPACE_GRAY])

    Chnage the colorspace of the first image to ``BGR``, the one of the second
    image to ``HSV`` and the one of the third image to ``grayscale`` (note
    that in the latter case the image will still have shape ``(H,W,3)``,
    not ``(H,W,1)``).

    """
    def _validate(arg, arg_name):
        if isinstance(arg, list):
            assert len(arg) == len(images), (
                "If `%s` is provided as a list it must have the same length "
                "as `images`. Got length %d, expected %d." % (
                    arg_name, len(arg), len(images)))
        else:
            assert ia.is_string(arg), (
                "Expected `%s` to be either a list of strings or a single "
                "string. Got type %s." % (arg_name, type(arg)))
            arg = [arg] * len(images)
        return arg

    to_colorspaces = _validate(to_colorspaces, "to_colorspaces")
    from_colorspaces = _validate(from_colorspaces, "from_colorspaces")

    gen = zip(images, to_colorspaces, from_colorspaces)
    for i, (image, to_colorspace, from_colorspace) in enumerate(gen):
        images[i] = change_colorspace_(image, to_colorspace, from_colorspace)
    return images


@ia.deprecated(alt_func="WithColorspace")
def InColorspace(to_colorspace, from_colorspace="RGB", children=None,
                 name=None, deterministic=False, random_state=None):
    """Convert images to another colorspace."""
    return WithColorspace(to_colorspace, from_colorspace, children, name,
                          deterministic, random_state)


class WithColorspace(meta.Augmenter):
    """
    Apply child augmenters within a specific colorspace.

    This augumenter takes a source colorspace A and a target colorspace B
    as well as children C. It changes images from A to B, then applies the
    child augmenters C and finally changes the colorspace back from B to A.
    See also ChangeColorspace() for more.

    dtype support::

        See :func:`imgaug.augmenters.color.change_colorspaces_`.

    Parameters
    ----------
    to_colorspace : str
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    children : None or Augmenter or list of Augmenters, optional
        See :func:`imgaug.augmenters.ChangeColorspace.__init__`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.WithColorspace(
    >>>     to_colorspace=iaa.CSPACE_HSV,
    >>>     from_colorspace=iaa.CSPACE_RGB,
    >>>     children=iaa.WithChannels(
    >>>         0,
    >>>         iaa.Add((0, 50))
    >>>     )
    >>> )

    Convert to ``HSV`` colorspace, add a value between ``0`` and ``50``
    (uniformly sampled per image) to the Hue channel, then convert back to the
    input colorspace (``RGB``).

    """

    def __init__(self, to_colorspace, from_colorspace=CSPACE_RGB, children=None,
                 name=None, deterministic=False, random_state=None):
        super(WithColorspace, self).__init__(
            name=name, deterministic=deterministic, random_state=random_state)

        self.to_colorspace = to_colorspace
        self.from_colorspace = from_colorspace
        self.children = meta.handle_children_list(children, self.name, "then")

    def _augment_images(self, images, random_state, parents, hooks):
        result = images
        if self._is_propagating(images, hooks, parents):
            result = change_colorspaces_(
                result,
                to_colorspaces=self.to_colorspace,
                from_colorspaces=self.from_colorspace)
            result = self.children.augment_images(
                images=result,
                parents=parents + [self],
                hooks=hooks
            )
            result = change_colorspaces_(
                result,
                to_colorspaces=self.from_colorspace,
                from_colorspaces=self.to_colorspace)
        return result

    def _augment_heatmaps(self, heatmaps, random_state, parents, hooks):
        return self._augment_nonimages(
            heatmaps, self.children.augment_heatmaps, parents,
            hooks)

    def _augment_segmentation_maps(self, segmaps, random_state, parents, hooks):
        return self._augment_nonimages(
            segmaps, self.children.augment_segmentation_maps,
            parents, hooks)

    def _augment_keypoints(self, keypoints_on_images, random_state, parents,
                           hooks):
        return self._augment_nonimages(
            keypoints_on_images, self.children.augment_keypoints, parents,
            hooks)

    # TODO add test for this
    def _augment_polygons(self, polygons_on_images, random_state, parents,
                          hooks):
        return self._augment_nonimages(
            polygons_on_images, self.children.augment_polygons, parents,
            hooks)

    def _augment_nonimages(self, augmentables, children_augfunc, parents,
                           hooks):
        if self._is_propagating(augmentables, hooks, parents):
            augmentables = children_augfunc(
                augmentables,
                parents=parents + [self],
                hooks=hooks
            )
        return augmentables

    def _is_propagating(self, augmentables, hooks, parents):
        return (hooks is None or hooks.is_propagating(
            augmentables, augmenter=self, parents=parents, default=True))

    def _to_deterministic(self):
        aug = self.copy()
        aug.children = aug.children.to_deterministic()
        aug.deterministic = True
        aug.random_state = self.random_state.derive_rng_()
        return aug

    def get_parameters(self):
        return [self.channels]

    def get_children_lists(self):
        return [self.children]

    def __str__(self):
        return (
            "WithColorspace(from_colorspace=%s, "
            "to_colorspace=%s, name=%s, children=[%s], deterministic=%s)" % (
                self.from_colorspace, self.to_colorspace, self.name,
                self.children, self.deterministic)
        )


# TODO Merge this into WithColorspace? A bit problematic due to int16
#      conversion that would make WithColorspace less flexible.
# TODO add option to choose overflow behaviour for hue and saturation channels,
#      e.g. clip, modulo or wrap
class WithHueAndSaturation(meta.Augmenter):
    """
    Apply child augmenters to hue and saturation channels.

    This augumenter takes an image in a source colorspace, converts
    it to HSV, extracts the H (hue) and S (saturation) channels,
    applies the provided child augmenters to these channels
    and finally converts back to the original colorspace.

    The image array generated by this augmenter and provided to its children
    is in ``int16`` (**sic!** only augmenters that can handle ``int16`` arrays
    can be children!). The hue channel is mapped to the value
    range ``[0, 255]``. Before converting back to the source colorspace, the
    saturation channel's values are clipped to ``[0, 255]``. A modulo operation
    is applied to the hue channel's values, followed by a mapping from
    ``[0, 255]`` to ``[0, 180]`` (and finally the colorspace conversion).

    dtype support::

        See :func:`imgaug.augmenters.color.change_colorspaces_`.

    Parameters
    ----------
    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    children : None or Augmenter or list of Augmenters, optional
        See :func:`imgaug.augmenters.ChangeColorspace.__init__`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.WithHueAndSaturation(
    >>>     iaa.WithChannels(0, iaa.Add((0, 50)))
    >>> )

    Create an augmenter that will add a random value between ``0`` and ``50``
    (uniformly sampled per image) hue channel in HSV colorspace. It
    automatically accounts for the hue being in angular representation, i.e.
    if the angle goes beyond 360 degrees, it will start again at 0 degrees.
    The colorspace is finally converted back to ``RGB`` (default setting).

    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.WithHueAndSaturation([
    >>>     iaa.WithChannels(0, iaa.Add((-30, 10))),
    >>>     iaa.WithChannels(1, [
    >>>         iaa.Multiply((0.5, 1.5)),
    >>>         iaa.LinearContrast((0.75, 1.25))
    >>>     ])
    >>> ])

    Create an augmenter that adds a random value sampled uniformly
    from the range ``[-30, 10]`` to the hue and multiplies the saturation
    by a random factor sampled uniformly from ``[0.5, 1.5]``. It also
    modifies the contrast of the saturation channel. After these steps,
    the ``HSV`` image is converted back to ``RGB``.

    """

    def __init__(self, children=None, from_colorspace="RGB", name=None,
                 deterministic=False, random_state=None):
        super(WithHueAndSaturation, self).__init__(
            name=name, deterministic=deterministic, random_state=random_state)

        self.children = meta.handle_children_list(children, self.name, "then")
        self.from_colorspace = from_colorspace

        # this dtype needs to be able to go beyond [0, 255] to e.g. accomodate
        # for Add or Multiply
        self._internal_dtype = np.int16

    def _augment_images(self, images, random_state, parents, hooks):
        result = images
        if self._is_propagating(images, hooks, parents):
            # RGB (or other source colorspace) -> HSV
            images_hsv = change_colorspaces_(
                images, CSPACE_HSV, self.from_colorspace)

            # HSV -> HS
            hue_and_sat = []
            for image_hsv in images_hsv:
                image_hsv = image_hsv.astype(np.int16)
                # project hue from [0,180] to [0,255] so that child augmenters
                # can assume the same value range for all channels
                hue = (
                    (image_hsv[:, :, 0].astype(np.float32) / 180.0) * 255.0
                ).astype(self._internal_dtype)
                saturation = image_hsv[:, :, 1]
                hue_and_sat.append(np.stack([hue, saturation], axis=-1))
            if ia.is_np_array(images_hsv):
                hue_and_sat = np.stack(hue_and_sat, axis=0)

            # apply child augmenters to HS
            hue_and_sat_aug = self.children.augment_images(
                images=hue_and_sat,
                parents=parents + [self],
                hooks=hooks
            )

            # postprocess augmented HS int16 data
            # hue: modulo to [0, 255] then project to [0, 360/2]
            # saturation: clip to [0, 255]
            # + convert to uint8
            # + re-attach V channel to HS
            hue_and_sat_proj = []
            for i, hs_aug in enumerate(hue_and_sat_aug):
                hue_aug = hs_aug[:, :, 0]
                sat_aug = hs_aug[:, :, 1]
                hue_aug = (
                    (np.mod(hue_aug, 255).astype(np.float32) / 255.0) * (360/2)
                ).astype(np.uint8)
                sat_aug = iadt.clip_(sat_aug, 0, 255).astype(np.uint8)
                hue_and_sat_proj.append(
                    np.stack([hue_aug, sat_aug, images_hsv[i][:, :, 2]],
                             axis=-1)
                )
            if ia.is_np_array(hue_and_sat_aug):
                hue_and_sat_proj = np.uint8(hue_and_sat_proj)

            # HSV -> RGB (or whatever the source colorspace was)
            result = change_colorspaces_(
                hue_and_sat_proj,
                to_colorspaces=self.from_colorspace,
                from_colorspaces=CSPACE_HSV)
        return result

    def _augment_heatmaps(self, heatmaps, random_state, parents, hooks):
        return self._augment_nonimages(
            heatmaps, self.children.augment_heatmaps, parents,
            hooks)

    def _augment_segmentation_maps(self, segmaps, random_state, parents,
                                   hooks):
        return self._augment_nonimages(
            segmaps, self.children.augment_segmentation_maps,
            parents, hooks)

    def _augment_keypoints(self, keypoints_on_images, random_state, parents,
                           hooks):
        return self._augment_nonimages(
            keypoints_on_images, self.children.augment_keypoints, parents,
            hooks)

    def _augment_polygons(self, polygons_on_images, random_state, parents,
                          hooks):
        return self._augment_nonimages(
            polygons_on_images, self.children.augment_polygons, parents,
            hooks)

    def _augment_nonimages(self, augmentables, children_augfunc, parents,
                           hooks):
        if self._is_propagating(augmentables, hooks, parents):
            augmentables = children_augfunc(
                augmentables,
                parents=parents + [self],
                hooks=hooks
            )
        return augmentables

    def _is_propagating(self, augmentables, hooks, parents):
        return (hooks is None or hooks.is_propagating(
            augmentables, augmenter=self, parents=parents, default=True))

    def _to_deterministic(self):
        aug = self.copy()
        aug.children = aug.children.to_deterministic()
        aug.deterministic = True
        aug.random_state = self.random_state.derive_rng_()
        return aug

    def get_parameters(self):
        return [self.from_colorspace]

    def get_children_lists(self):
        return [self.children]

    def __str__(self):
        return (
            "WithHueAndSaturation(from_colorspace=%s, "
            "name=%s, children=[%s], deterministic=%s)" % (
                self.from_colorspace, self.name,
                self.children, self.deterministic)
        )


class MultiplyHueAndSaturation(WithHueAndSaturation):
    """
    Multipy hue and saturation by random values.

    The augmenter first transforms images to HSV colorspace, then multiplies
    the pixel values in the H and S channels and afterwards converts back to
    RGB.

    This augmenter is a wrapper around ``WithHueAndSaturation``.

    dtype support::

        See `imgaug.augmenters.color.WithHueAndSaturation`.

    Parameters
    ----------
    mul : None or number or tuple of number or list of number or imgaug.parameters.StochasticParameter, optional
        Multiplier with which to multiply all hue *and* saturation values of
        all pixels.
        It is expected to be in the range ``-10.0`` to ``+10.0``.
        Note that values of ``0.0`` or lower will remove all saturation.

            * If this is ``None``, `mul_hue` and/or `mul_saturation`
              may be set to values other than ``None``.
            * If a number, then that multiplier will be used for all images.
            * If a tuple ``(a, b)``, then a value from the continuous
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    mul_hue : None or number or tuple of number or list of number or imgaug.parameters.StochasticParameter, optional
        Multiplier with which to multiply all hue values.
        This is expected to be in the range ``-10.0`` to ``+10.0`` and will
        automatically be projected to an angular representation using
        ``(hue/255) * (360/2)`` (OpenCV's hue representation is in the
        range ``[0, 180]`` instead of ``[0, 360]``).
        Only this or `mul` may be set, not both.

            * If this and `mul_saturation` are both ``None``, `mul` may
              be set to a non-``None`` value.
            * If a number, then that multiplier will be used for all images.
            * If a tuple ``(a, b)``, then a value from the continuous
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    mul_saturation : None or number or tuple of number or list of number or imgaug.parameters.StochasticParameter, optional
        Multiplier with which to multiply all saturation values.
        It is expected to be in the range ``0.0`` to ``+10.0``.
        Only this or `mul` may be set, not both.

            * If this and `mul_hue` are both ``None``, `mul` may
              be set to a non-``None`` value.
            * If a number, then that value will be used for all images.
            * If a tuple ``(a, b)``, then a value from the continuous
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    per_channel : bool or float, optional
        Whether to sample per image only one value from `mul` and use it for
        both hue and saturation (``False``) or to sample independently one
        value for hue and one for saturation (``True``).
        If this value is a float ``p``, then for ``p`` percent of all images
        `per_channel` will be treated as ``True``, otherwise as ``False``.

        This parameter has no effect if `mul_hue` and/or `mul_saturation`
        are used instead of `mul`.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.MultiplyHueAndSaturation((0.5, 1.5), per_channel=True)

    Multiply hue and saturation by random values between ``0.5`` and ``1.5``
    (independently per channel and the same value for all pixels within
    that channel). The hue will be automatically projected to an angular
    representation.

    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.MultiplyHueAndSaturation(mul_hue=(0.5, 1.5))

    Multiply only the hue by random values between ``0.5`` and ``1.5``.

    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.MultiplyHueAndSaturation(mul_saturation=(0.5, 1.5))

    Multiply only the saturation by random values between ``0.5`` and ``1.5``.

    """

    def __init__(self, mul=None, mul_hue=None, mul_saturation=None,
                 per_channel=False, from_colorspace="RGB",
                 name=None, deterministic=False,
                 random_state=None):
        if mul is not None:
            assert mul_hue is None, (
                "`mul_hue` may not be set if `mul` is set. "
                "It is set to: %s (type: %s)." % (
                    str(mul_hue), type(mul_hue)))
            assert mul_saturation is None, (
                "`mul_saturation` may not be set if `mul` is set. "
                "It is set to: %s (type: %s)." % (
                    str(mul_saturation), type(mul_saturation)))
            mul = iap.handle_continuous_param(
                mul, "mul", value_range=(-10.0, 10.0), tuple_to_uniform=True,
                list_to_choice=True)
        else:
            if mul_hue is not None:
                mul_hue = iap.handle_continuous_param(
                    mul_hue, "mul_hue", value_range=(-10.0, 10.0),
                    tuple_to_uniform=True, list_to_choice=True)
            if mul_saturation is not None:
                mul_saturation = iap.handle_continuous_param(
                    mul_saturation, "mul_saturation", value_range=(0.0, 10.0),
                    tuple_to_uniform=True, list_to_choice=True)

        if random_state is None:
            rss = [None] * 5
        else:
            rss = random_state.derive_rngs_(5)

        children = []
        if mul is not None:
            children.append(
                arithmetic.Multiply(
                    mul,
                    per_channel=per_channel,
                    name="%s-Multiply" % (name,),
                    random_state=rss[0],
                    deterministic=deterministic
                )
            )
        else:
            if mul_hue is not None:
                children.append(
                    meta.WithChannels(
                        0,
                        arithmetic.Multiply(
                            mul_hue,
                            name="%s-MultiplyHue" % (name,),
                            random_state=rss[0],
                            deterministic=deterministic
                        ),
                        name="%s-WithChannelsHue" % (name,),
                        random_state=rss[1],
                        deterministic=deterministic
                    )
                )
            if mul_saturation is not None:
                children.append(
                    meta.WithChannels(
                        1,
                        arithmetic.Multiply(
                            mul_saturation,
                            name="%s-MultiplySaturation" % (name,),
                            random_state=rss[2],
                            deterministic=deterministic
                        ),
                        name="%s-WithChannelsSaturation" % (name,),
                        random_state=rss[3],
                        deterministic=deterministic
                    )
                )

        super(MultiplyHueAndSaturation, self).__init__(
            children,
            from_colorspace=from_colorspace,
            name=name,
            random_state=rss[4],
            deterministic=deterministic
        )


class MultiplyHue(MultiplyHueAndSaturation):
    """
    Multiply the hue of images by random values.

    The augmenter first transforms images to HSV colorspace, then multiplies
    the pixel values in the H channel and afterwards converts back to
    RGB.

    This augmenter is a shortcut for ``MultiplyHueAndSaturation(mul_hue=...)``.

    dtype support::

        See `imgaug.augmenters.color.MultiplyHueAndSaturation`.

    Parameters
    ----------
    mul : number or tuple of number or list of number or imgaug.parameters.StochasticParameter, optional
        Multiplier with which to multiply all hue values.
        This is expected to be in the range ``-10.0`` to ``+10.0`` and will
        automatically be projected to an angular representation using
        ``(hue/255) * (360/2)`` (OpenCV's hue representation is in the
        range ``[0, 180]`` instead of ``[0, 360]``).
        Only this or `mul` may be set, not both.

            * If a number, then that multiplier will be used for all images.
            * If a tuple ``(a, b)``, then a value from the continuous
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.MultiplyHue((0.5, 1.5))

    Multiply the hue channel of images using random values between ``0.5``
    and ``1.5``.

    """

    def __init__(self, mul=(-1.0, 1.0), from_colorspace="RGB", name=None,
                 deterministic=False, random_state=None):
        super(MultiplyHue, self).__init__(
            mul_hue=mul,
            from_colorspace=from_colorspace,
            name=name,
            deterministic=deterministic,
            random_state=random_state)


class MultiplySaturation(MultiplyHueAndSaturation):
    """
    Multiply the saturation of images by random values.

    The augmenter first transforms images to HSV colorspace, then multiplies
    the pixel values in the H channel and afterwards converts back to
    RGB.

    This augmenter is a shortcut for
    ``MultiplyHueAndSaturation(mul_saturation=...)``.

    dtype support::

        See `imgaug.augmenters.color.MultiplyHueAndSaturation`.

    Parameters
    ----------
    mul : number or tuple of number or list of number or imgaug.parameters.StochasticParameter, optional
        Multiplier with which to multiply all saturation values.
        It is expected to be in the range ``0.0`` to ``+10.0``.

            * If a number, then that value will be used for all images.
            * If a tuple ``(a, b)``, then a value from the continuous
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.MultiplySaturation((0.5, 1.5))

    Multiply the saturation channel of images using random values between
    ``0.5`` and ``1.5``.

    """

    def __init__(self, mul=(0.0, 3.0), from_colorspace="RGB", name=None,
                 deterministic=False, random_state=None):
        super(MultiplySaturation, self).__init__(
            mul_saturation=mul,
            from_colorspace=from_colorspace,
            name=name,
            deterministic=deterministic,
            random_state=random_state)


# TODO removed deterministic and random_state here as parameters, because this
# function creates multiple child augmenters. not sure if this is sensible
# (give them all the same random state instead?)
# TODO this is for now deactivated, because HSV images returned by opencv have
#      value range 0-180 for the hue channel
#      and are supposed to be angular representations, i.e. if values go below
#      0 or above 180 they are supposed to overflow
#      to 180 and 0
"""
def AddToHueAndSaturation(value=0, per_channel=False, from_colorspace="RGB",
                          channels=[0, 1], name=None):  # pylint: disable=locally-disabled, dangerous-default-value, line-too-long
    ""
    Augmenter that transforms images into HSV space, selects the H and S
    channels and then adds a given range of values to these.

    Parameters
    ----------
    value : int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        See :func:`imgaug.augmenters.arithmetic.Add.__init__()`.

    per_channel : bool or float, optional
        See :func:`imgaug.augmenters.arithmetic.Add.__init__()`.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    channels : int or list of int or None, optional
        See :func:`imgaug.augmenters.meta.WithChannels.__init__()`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> aug = AddToHueAndSaturation((-20, 20), per_channel=True)

    Adds random values between -20 and 20 to the hue and saturation
    (independently per channel and the same value for all pixels within
    that channel).

    ""
    if name is None:
        name = "Unnamed%s" % (ia.caller_name(),)

    return WithColorspace(
        to_colorspace="HSV",
        from_colorspace=from_colorspace,
        children=meta.WithChannels(
            channels=channels,
            children=arithmetic.Add(value=value, per_channel=per_channel)
        ),
        name=name
    )
"""


class AddToHueAndSaturation(meta.Augmenter):
    """
    Increases or decreases hue and saturation by random values.

    The augmenter first transforms images to HSV colorspace, then adds random
    values to the H and S channels and afterwards converts back to RGB.

    This augmenter is faster than using ``WithHueAndSaturation`` in combination
    with ``Add``.

    TODO add float support

    dtype support::

        See :func:`imgaug.augmenters.color.change_colorspace_`.

    Parameters
    ----------
    value : None or int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        Value to add to the hue *and* saturation of all pixels.
        It is expected to be in the range ``-255`` to ``+255``.

            * If this is ``None``, `value_hue` and/or `value_saturation`
              may be set to values other than ``None``.
            * If an integer, then that value will be used for all images.
            * If a tuple ``(a, b)``, then a value from the discrete
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    value_hue : None or int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        Value to add to the hue of all pixels.
        This is expected to be in the range ``-255`` to ``+255`` and will
        automatically be projected to an angular representation using
        ``(hue/255) * (360/2)`` (OpenCV's hue representation is in the
        range ``[0, 180]`` instead of ``[0, 360]``).
        Only this or `value` may be set, not both.

            * If this and `value_saturation` are both ``None``, `value` may
              be set to a non-``None`` value.
            * If an integer, then that value will be used for all images.
            * If a tuple ``(a, b)``, then a value from the discrete
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    value_saturation : None or int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        Value to add to the saturation of all pixels.
        It is expected to be in the range ``-255`` to ``+255``.
        Only this or `value` may be set, not both.

            * If this and `value_hue` are both ``None``, `value` may
              be set to a non-``None`` value.
            * If an integer, then that value will be used for all images.
            * If a tuple ``(a, b)``, then a value from the discrete
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    per_channel : bool or float, optional
        Whether to sample per image only one value from `value` and use it for
        both hue and saturation (``False``) or to sample independently one
        value for hue and one for saturation (``True``).
        If this value is a float ``p``, then for ``p`` percent of all images
        `per_channel` will be treated as ``True``, otherwise as ``False``.

        This parameter has no effect is `value_hue` and/or `value_saturation`
        are used instead of `value`.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.AddToHueAndSaturation((-50, 50), per_channel=True)

    Add random values between ``-50`` and ``50`` to the hue and saturation
    (independently per channel and the same value for all pixels within
    that channel).

    """

    _LUT_CACHE = None

    def __init__(self, value=None, value_hue=None, value_saturation=None,
                 per_channel=False, from_colorspace="RGB",
                 name=None, deterministic=False, random_state=None):
        super(AddToHueAndSaturation, self).__init__(
            name=name, deterministic=deterministic, random_state=random_state)

        self.value = self._handle_value_arg(value, value_hue, value_saturation)
        self.value_hue = self._handle_value_hue_arg(value_hue)
        self.value_saturation = self._handle_value_saturation_arg(
            value_saturation)
        self.per_channel = iap.handle_probability_param(per_channel,
                                                        "per_channel")
        self.from_colorspace = from_colorspace
        self.backend = "cv2"

        # precompute tables for cv2.LUT
        if self.backend == "cv2" and self._LUT_CACHE is None:
            self._LUT_CACHE = self._generate_lut_table()

    def _draw_samples(self, augmentables, random_state):
        nb_images = len(augmentables)
        rss = random_state.duplicate(2)

        if self.value is not None:
            per_channel = self.per_channel.draw_samples(
                (nb_images,), random_state=rss[0])
            per_channel = (per_channel > 0.5)

            samples = self.value.draw_samples(
                (nb_images, 2), random_state=rss[1]).astype(np.int32)
            assert -255 <= samples[0, 0] <= 255, (
                "Expected values sampled from `value` in "
                "AddToHueAndSaturation to be in range [-255, 255], "
                "but got %.8f." % (samples[0, 0]))

            samples_hue = samples[:, 0]
            samples_saturation = np.copy(samples[:, 0])
            samples_saturation[per_channel] = samples[per_channel, 1]
        else:
            if self.value_hue is not None:
                samples_hue = self.value_hue.draw_samples(
                    (nb_images,), random_state=rss[0]).astype(np.int32)
            else:
                samples_hue = np.zeros((nb_images,), dtype=np.int32)

            if self.value_saturation is not None:
                samples_saturation = self.value_saturation.draw_samples(
                    (nb_images,), random_state=rss[1]).astype(np.int32)
            else:
                samples_saturation = np.zeros((nb_images,), dtype=np.int32)

        # project hue to angular representation
        # OpenCV uses range [0, 180] for the hue
        samples_hue = (
            (samples_hue.astype(np.float32) / 255.0) * (360/2)
        ).astype(np.int32)

        return samples_hue, samples_saturation

    def _augment_images(self, images, random_state, parents, hooks):
        input_dtypes = iadt.copy_dtypes_for_restore(images, force_list=True)

        result = images

        # surprisingly, placing this here seems to be slightly slower than
        # placing it inside the loop
        # if isinstance(images_hsv, list):
        #    images_hsv = [img.astype(np.int32) for img in images_hsv]
        # else:
        #    images_hsv = images_hsv.astype(np.int32)

        images_hsv = change_colorspaces_(
            images, CSPACE_HSV, self.from_colorspace)
        samples = self._draw_samples(images, random_state)
        hues = samples[0]
        saturations = samples[1]

        # this is needed if no cache for LUT is used:
        # value_range = np.arange(0, 256, dtype=np.int16)

        gen = enumerate(zip(images_hsv, hues, saturations))
        for i, (image_hsv, hue_i, saturation_i) in gen:
            if self.backend == "cv2":
                image_hsv = self._transform_image_cv2(
                    image_hsv, hue_i, saturation_i)
            else:
                image_hsv = self._transform_image_numpy(
                    image_hsv, hue_i, saturation_i)

            image_hsv = image_hsv.astype(input_dtypes[i])
            image_rgb = change_colorspace_(
                image_hsv,
                to_colorspace=self.from_colorspace,
                from_colorspace=CSPACE_HSV)
            result[i] = image_rgb

        return result

    def _transform_image_cv2(self, image_hsv, hue, saturation):
        # this has roughly the same speed as the numpy backend
        # for 64x64 and is about 25% faster for 224x224

        # code without using cache:
        # table_hue = np.mod(value_range + sample_hue, 180)
        # table_saturation = np.clip(value_range + sample_saturation, 0, 255)

        # table_hue = table_hue.astype(np.uint8, copy=False)
        # table_saturation = table_saturation.astype(np.uint8, copy=False)

        # image_hsv[..., 0] = cv2.LUT(image_hsv[..., 0], table_hue)
        # image_hsv[..., 1] = cv2.LUT(image_hsv[..., 1], table_saturation)

        # code with using cache (at best maybe 10% faster for 64x64):
        table_hue = self._LUT_CACHE[0]
        table_saturation = self._LUT_CACHE[1]

        image_hsv[..., 0] = cv2.LUT(
            image_hsv[..., 0], table_hue[255+int(hue)])
        image_hsv[..., 1] = cv2.LUT(
            image_hsv[..., 1], table_saturation[255+int(saturation)])

        return image_hsv

    @classmethod
    def _transform_image_numpy(cls, image_hsv, hue, saturation):
        # int16 seems to be slightly faster than int32
        image_hsv = image_hsv.astype(np.int16)
        # np.mod() works also as required here for negative values
        image_hsv[..., 0] = np.mod(image_hsv[..., 0] + hue, 180)
        image_hsv[..., 1] = np.clip(
            image_hsv[..., 1] + saturation, 0, 255)
        return image_hsv

    def get_parameters(self):
        return [self.value, self.value_hue, self.value_saturation,
                self.per_channel, self.from_colorspace]

    @classmethod
    def _handle_value_arg(cls, value, value_hue, value_saturation):
        if value is not None:
            assert value_hue is None, (
                "`value_hue` may not be set if `value` is set. "
                "It is set to: %s (type: %s)." % (
                    str(value_hue), type(value_hue)))
            assert value_saturation is None, (
                "`value_saturation` may not be set if `value` is set. "
                "It is set to: %s (type: %s)." % (
                    str(value_saturation), type(value_saturation)))
            return iap.handle_discrete_param(
                value, "value", value_range=(-255, 255), tuple_to_uniform=True,
                list_to_choice=True, allow_floats=False)

        return None

    @classmethod
    def _handle_value_hue_arg(cls, value_hue):
        if value_hue is not None:
            # we don't have to verify here that value is None, as the
            # exclusivity was already ensured in _handle_value_arg()
            return iap.handle_discrete_param(
                value_hue, "value_hue", value_range=(-255, 255),
                tuple_to_uniform=True, list_to_choice=True, allow_floats=False)

        return None

    @classmethod
    def _handle_value_saturation_arg(cls, value_saturation):
        if value_saturation is not None:
            # we don't have to verify here that value is None, as the
            # exclusivity was already ensured in _handle_value_arg()
            return iap.handle_discrete_param(
                value_saturation, "value_saturation", value_range=(-255, 255),
                tuple_to_uniform=True, list_to_choice=True, allow_floats=False)
        return None

    @classmethod
    def _generate_lut_table(cls):
        # TODO Changing the dtype here to int8 makes gen test for this method
        #      fail, but all other tests still succeed. How can this be?
        #      The dtype was verified to remain int8, having min & max at
        #      -128 & 127.
        dt = np.uint8
        table = (np.zeros((256*2, 256), dtype=dt),
                 np.zeros((256*2, 256), dtype=dt))
        value_range = np.arange(0, 256, dtype=np.int16)
        # this could be done slightly faster by vectorizing the loop
        for i in sm.xrange(-255, 255+1):
            table_hue = np.mod(value_range + i, 180)
            table_saturation = np.clip(value_range + i, 0, 255)
            table[0][255+i, :] = table_hue
            table[1][255+i, :] = table_saturation
        return table


class AddToHue(AddToHueAndSaturation):
    """
    Add random values to the hue of images.

    The augmenter first transforms images to HSV colorspace, then adds random
    values to the H channel and afterwards converts back to RGB.

    If you want to change both the hue and the saturation, it is recommended
    to use ``AddToHueAndSaturation`` as otherwise the image will be
    converted twice to HSV and back to RGB.

    This augmenter is a shortcut for ``AddToHueAndSaturation(value_hue=...)``.

    dtype support::

        See `imgaug.augmenters.color.AddToHueAndSaturation`.

    Parameters
    ----------
    value : None or int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        Value to add to the hue of all pixels.
        This is expected to be in the range ``-255`` to ``+255`` and will
        automatically be projected to an angular representation using
        ``(hue/255) * (360/2)`` (OpenCV's hue representation is in the
        range ``[0, 180]`` instead of ``[0, 360]``).

            * If an integer, then that value will be used for all images.
            * If a tuple ``(a, b)``, then a value from the discrete
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.AddToHue((-50, 50))

    Sample random values from the discrete uniform range ``[-50..50]``,
    convert them to angular representation and add them to the hue, i.e.
    to the ``H`` channel in ``HSV`` colorspace.

    """

    def __init__(self, value=(-255, 255), from_colorspace=CSPACE_RGB,
                 name=None, deterministic=False, random_state=None):
        super(AddToHue, self).__init__(
            value_hue=value,
            from_colorspace=from_colorspace,
            name=name,
            deterministic=deterministic,
            random_state=random_state)


class AddToSaturation(AddToHueAndSaturation):
    """
    Add random values to the saturation of images.

    The augmenter first transforms images to HSV colorspace, then adds random
    values to the S channel and afterwards converts back to RGB.

    If you want to change both the hue and the saturation, it is recommended
    to use ``AddToHueAndSaturation`` as otherwise the image will be
    converted twice to HSV and back to RGB.

    This augmenter is a shortcut for
    ``AddToHueAndSaturation(value_saturation=...)``.

    dtype support::

        See `imgaug.augmenters.color.AddToHueAndSaturation`.

    Parameters
    ----------
    value : None or int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        Value to add to the saturation of all pixels.
        It is expected to be in the range ``-255`` to ``+255``.

            * If an integer, then that value will be used for all images.
            * If a tuple ``(a, b)``, then a value from the discrete
              range ``[a, b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, then a value will be sampled from that
              parameter per image.

    from_colorspace : str, optional
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.AddToSaturation((-50, 50))

    Sample random values from the discrete uniform range ``[-50..50]``,
    and add them to the saturation, i.e. to the ``S`` channel in ``HSV``
    colorspace.

    """

    def __init__(self, value=(-75, 75), from_colorspace="RGB", name=None,
                 deterministic=False, random_state=None):
        super(AddToSaturation, self).__init__(
            value_saturation=value,
            from_colorspace=from_colorspace,
            name=name,
            deterministic=deterministic,
            random_state=random_state)


# TODO tests
# TODO rename to ChangeColorspace3D and then introduce ChangeColorspace, which
#      does not enforce 3d images?
class ChangeColorspace(meta.Augmenter):
    """
    Augmenter to change the colorspace of images.

    .. note ::

        This augmenter is not tested. Some colorspaces might work, others
        might not.

    ..note ::

        This augmenter tries to project the colorspace value range on
        0-255. It outputs dtype=uint8 images.

    dtype support::

        See :func:`imgaug.augmenters.color.change_colorspace_`.

    Parameters
    ----------
    to_colorspace : str or list of str or imgaug.parameters.StochasticParameter
        The target colorspace.
        Allowed strings are: ``RGB``, ``BGR``, ``GRAY``, ``CIE``, ``YCrCb``,
        ``HSV``, ``HLS``, ``Lab``, ``Luv``.
        These are also accessible via
        ``imgaug.augmenters.color.CSPACE_<NAME>``,
        e.g. ``imgaug.augmenters.CSPACE_YCrCb``.

            * If a string, it must be among the allowed colorspaces.
            * If a list, it is expected to be a list of strings, each one
              being an allowed colorspace. A random element from the list
              will be chosen per image.
            * If a StochasticParameter, it is expected to return string. A new
              sample will be drawn per image.

    from_colorspace : str, optional
        The source colorspace (of the input images).
        See `to_colorspace`. Only a single string is allowed.

    alpha : number or tuple of number or list of number or imgaug.parameters.StochasticParameter, optional
        The alpha value of the new colorspace when overlayed over the
        old one. A value close to 1.0 means that mostly the new
        colorspace is visible. A value close to 0.0 means, that mostly the
        old image is visible.

            * If an int or float, exactly that value will be used.
            * If a tuple ``(a, b)``, a random value from the range
              ``a <= x <= b`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, a value will be sampled from the
              parameter per image.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    """

    # TODO mark these as deprecated
    RGB = CSPACE_RGB
    BGR = CSPACE_BGR
    GRAY = CSPACE_GRAY
    CIE = CSPACE_CIE
    YCrCb = CSPACE_YCrCb
    HSV = CSPACE_HSV
    HLS = CSPACE_HLS
    Lab = CSPACE_Lab
    Luv = CSPACE_Luv
    COLORSPACES = {RGB, BGR, GRAY, CIE, YCrCb, HSV, HLS, Lab, Luv}
    # TODO access cv2 COLOR_ variables directly instead of indirectly via
    #      dictionary mapping
    CV_VARS = {
        # RGB
        "RGB2BGR": cv2.COLOR_RGB2BGR,
        "RGB2GRAY": cv2.COLOR_RGB2GRAY,
        "RGB2CIE": cv2.COLOR_RGB2XYZ,
        "RGB2YCrCb": cv2.COLOR_RGB2YCR_CB,
        "RGB2HSV": cv2.COLOR_RGB2HSV,
        "RGB2HLS": cv2.COLOR_RGB2HLS,
        "RGB2Lab": cv2.COLOR_RGB2LAB,
        "RGB2Luv": cv2.COLOR_RGB2LUV,
        # BGR
        "BGR2RGB": cv2.COLOR_BGR2RGB,
        "BGR2GRAY": cv2.COLOR_BGR2GRAY,
        "BGR2CIE": cv2.COLOR_BGR2XYZ,
        "BGR2YCrCb": cv2.COLOR_BGR2YCR_CB,
        "BGR2HSV": cv2.COLOR_BGR2HSV,
        "BGR2HLS": cv2.COLOR_BGR2HLS,
        "BGR2Lab": cv2.COLOR_BGR2LAB,
        "BGR2Luv": cv2.COLOR_BGR2LUV,
        # HSV
        "HSV2RGB": cv2.COLOR_HSV2RGB,
        "HSV2BGR": cv2.COLOR_HSV2BGR,
        # HLS
        "HLS2RGB": cv2.COLOR_HLS2RGB,
        "HLS2BGR": cv2.COLOR_HLS2BGR,
        # Lab
        "Lab2RGB": (
            cv2.COLOR_Lab2RGB
            if hasattr(cv2, "COLOR_Lab2RGB") else cv2.COLOR_LAB2RGB),
        "Lab2BGR": (
            cv2.COLOR_Lab2BGR
            if hasattr(cv2, "COLOR_Lab2BGR") else cv2.COLOR_LAB2BGR)
    }

    def __init__(self, to_colorspace, from_colorspace=CSPACE_RGB, alpha=1.0,
                 name=None, deterministic=False, random_state=None):
        super(ChangeColorspace, self).__init__(
            name=name, deterministic=deterministic, random_state=random_state)

        # TODO somehow merge this with Alpha augmenter?
        self.alpha = iap.handle_continuous_param(
            alpha, "alpha", value_range=(0, 1.0), tuple_to_uniform=True,
            list_to_choice=True)

        if ia.is_string(to_colorspace):
            assert to_colorspace in CSPACE_ALL, (
                "Expected 'to_colorspace' to be one of %s. Got %s." % (
                    CSPACE_ALL, to_colorspace))
            self.to_colorspace = iap.Deterministic(to_colorspace)
        elif ia.is_iterable(to_colorspace):
            all_strings = all(
                [ia.is_string(colorspace) for colorspace in to_colorspace])
            assert all_strings, (
                "Expected list of 'to_colorspace' to only contain strings. "
                "Got types %s." % (
                    ", ".join([str(type(v)) for v in to_colorspace])))
            all_valid = all(
                [(colorspace in CSPACE_ALL)
                 for colorspace in to_colorspace])
            assert all_valid, (
                "Expected list of 'to_colorspace' to only contain strings "
                "that are in %s. Got strings %s." % (
                    CSPACE_ALL, to_colorspace))
            self.to_colorspace = iap.Choice(to_colorspace)
        elif isinstance(to_colorspace, iap.StochasticParameter):
            self.to_colorspace = to_colorspace
        else:
            raise Exception("Expected to_colorspace to be string, list of "
                            "strings or StochasticParameter, got %s." % (
                                type(to_colorspace),))

        assert ia.is_string(from_colorspace), (
            "Expected from_colorspace to be a single string, "
            "got type %s." % (type(from_colorspace),))
        assert from_colorspace in CSPACE_ALL, (
            "Expected from_colorspace to be one of: %s. Got: %s." % (
                ", ".join(CSPACE_ALL), from_colorspace))
        assert from_colorspace != CSPACE_GRAY, (
            "Cannot convert from grayscale images to other colorspaces.")
        self.from_colorspace = from_colorspace

        # epsilon value to check if alpha is close to 1.0 or 0.0
        self.eps = 0.001

    def _draw_samples(self, n_augmentables, random_state):
        rss = random_state.duplicate(2)
        alphas = self.alpha.draw_samples(
            (n_augmentables,), random_state=rss[0])
        to_colorspaces = self.to_colorspace.draw_samples(
            (n_augmentables,), random_state=rss[1])
        return alphas, to_colorspaces

    def _augment_images(self, images, random_state, parents, hooks):
        result = images
        nb_images = len(images)
        alphas, to_colorspaces = self._draw_samples(nb_images, random_state)
        for i in sm.xrange(nb_images):
            alpha = alphas[i]
            to_colorspace = to_colorspaces[i]
            image = images[i]

            assert to_colorspace in CSPACE_ALL, (
                "Expected 'to_colorspace' to be one of %s. Got %s." % (
                    CSPACE_ALL, to_colorspace))

            if alpha <= self.eps or self.from_colorspace == to_colorspace:
                pass  # no change necessary
            else:
                image_aug = change_colorspace_(image, to_colorspace,
                                               self.from_colorspace)
                result[i] = blend.blend_alpha(image_aug, image, alpha, self.eps)

        return images

    def get_parameters(self):
        return [self.to_colorspace, self.alpha]


# TODO rename to Grayscale3D and add Grayscale that keeps the image at 1D?
class Grayscale(ChangeColorspace):
    """Augmenter to convert images to their grayscale versions.

    .. note ::

        Number of output channels is still ``3``, i.e. this augmenter just
        "removes" color.

    TODO check dtype support

    dtype support::

        See :func:`imgaug.augmenters.color.change_colorspace_`.

    Parameters
    ----------
    alpha : number or tuple of number or list of number or imgaug.parameters.StochasticParameter, optional
        The alpha value of the grayscale image when overlayed over the
        old image. A value close to 1.0 means, that mostly the new grayscale
        image is visible. A value close to 0.0 means, that mostly the
        old image is visible.

            * If a number, exactly that value will always be used.
            * If a tuple ``(a, b)``, a random value from the range
              ``a <= x <= b`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a StochasticParameter, a value will be sampled from the
              parameter per image.

    from_colorspace : str, optional
        The source colorspace (of the input images).
        Allowed strings are: ``RGB``, ``BGR``, ``GRAY``, ``CIE``, ``YCrCb``,
        ``HSV``, ``HLS``, ``Lab``, ``Luv``.
        See :func:`imgaug.augmenters.color.change_colorspace_`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.Grayscale(alpha=1.0)

    Creates an augmenter that turns images to their grayscale versions.

    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.Grayscale(alpha=(0.0, 1.0))

    Creates an augmenter that turns images to their grayscale versions with
    an alpha value in the range ``0 <= alpha <= 1``. An alpha value of 0.5 would
    mean, that the output image is 50 percent of the input image and 50
    percent of the grayscale image (i.e. 50 percent of color removed).

    """

    def __init__(self, alpha=0, from_colorspace=CSPACE_RGB,
                 name=None, deterministic=False, random_state=None):
        super(Grayscale, self).__init__(
            to_colorspace=CSPACE_GRAY,
            alpha=alpha,
            from_colorspace=from_colorspace,
            name=name,
            deterministic=deterministic,
            random_state=random_state)


@six.add_metaclass(ABCMeta)
class _AbstractColorQuantization(meta.Augmenter):
    def __init__(self,
                 n_colors=(2, 16), from_colorspace=CSPACE_RGB,
                 to_colorspace=[CSPACE_RGB, CSPACE_Lab],
                 max_size=128,
                 interpolation="linear",
                 name=None, deterministic=False, random_state=None):
        # pylint: disable=dangerous-default-value
        super(_AbstractColorQuantization, self).__init__(
            name=name, deterministic=deterministic, random_state=random_state)

        self.n_colors = iap.handle_discrete_param(
            n_colors, "n_colors", value_range=(2, None),
            tuple_to_uniform=True, list_to_choice=True, allow_floats=False)
        self.from_colorspace = from_colorspace
        self.to_colorspace = to_colorspace
        self.max_size = max_size
        self.interpolation = interpolation

    def _draw_samples(self, n_augmentables, random_state):
        n_colors = self.n_colors.draw_samples((n_augmentables,), random_state)

        # Quantizing down to less than 2 colors does not make any sense.
        # Note that we canget <2 here despite the value range constraint
        # in __init__ if a StochasticParameter was provided, e.g.
        # Deterministic(1) is currently not verified.
        n_colors = np.clip(n_colors, 2, None)

        return n_colors

    def _augment_images(self, images, random_state, parents, hooks):
        rss = random_state.duplicate(1 + len(images))
        n_colors = self._draw_samples(len(images), rss[-1])

        result = images
        for i, image in enumerate(images):
            result[i] = self._augment_single_image(image, n_colors[i], rss[i])
        return result

    def _augment_single_image(self, image, n_colors, random_state):
        assert image.shape[-1] in [1, 3, 4], (
            "Expected image with 1, 3 or 4 channels, "
            "got %d (shape: %s)." % (image.shape[-1], image.shape))

        orig_shape = image.shape
        image = self._ensure_max_size(
            image, self.max_size, self.interpolation)

        if image.shape[-1] == 1:
            # 2D image
            image_aug = self._quantize(image, n_colors)
        else:
            # 3D image with 3 or 4 channels
            alpha_channel = None
            if image.shape[-1] == 4:
                alpha_channel = image[:, :, 3:4]
                image = image[:, :, 0:3]

            if self.to_colorspace is None:
                cs = meta.Noop()
                cs_inv = meta.Noop()
            else:
                # TODO quite hacky to recover the sampled to_colorspace here
                #      by accessing _draw_samples(). Would be better to have
                #      an inverse augmentation method in ChangeColorspace.
                cs = ChangeColorspace(
                    from_colorspace=self.from_colorspace,
                    to_colorspace=self.to_colorspace,
                    random_state=random_state.copy(),
                    deterministic=True)
                _, to_colorspaces = cs._draw_samples(
                    1, random_state.copy())
                cs_inv = ChangeColorspace(
                    from_colorspace=to_colorspaces[0],
                    to_colorspace=self.from_colorspace,
                    random_state=random_state.copy(),
                    deterministic=True)

            image_tf = cs.augment_image(image)
            image_tf_aug = self._quantize(image_tf, n_colors)
            image_aug = cs_inv.augment_image(image_tf_aug)

            if alpha_channel is not None:
                image_aug = np.concatenate([image_aug, alpha_channel], axis=2)

        if orig_shape != image_aug.shape:
            image_aug = ia.imresize_single_image(
                image_aug,
                orig_shape[0:2],
                interpolation=self.interpolation)

        return image_aug

    @abstractmethod
    def _quantize(self, image, n_colors):
        """Apply the augmenter-specific quantization function to an image."""

    def get_parameters(self):
        return [self.n_colors,
                self.from_colorspace,
                self.to_colorspace,
                self.max_size,
                self.interpolation]

    # TODO this is the same function as in Superpixels._ensure_max_size
    #      make DRY
    @classmethod
    def _ensure_max_size(cls, image, max_size, interpolation):
        if max_size is not None:
            size = max(image.shape[0], image.shape[1])
            if size > max_size:
                resize_factor = max_size / size
                new_height = int(image.shape[0] * resize_factor)
                new_width = int(image.shape[1] * resize_factor)
                image = ia.imresize_single_image(
                    image,
                    (new_height, new_width),
                    interpolation=interpolation)
        return image


class KMeansColorQuantization(_AbstractColorQuantization):
    """
    Quantize colors using k-Means clustering.

    This "collects" the colors from the input image, groups them into
    ``k`` clusters using k-Means clustering and replaces the colors in the
    input image using the cluster centroids.

    This is slower than ``UniformColorQuantization``, but adapts dynamically
    to the color range in the input image.

    .. note::

        This augmenter expects input images to be either grayscale
        or to have 3 or 4 channels and use colorspace `from_colorspace`. If
        images have 4 channels, it is assumed that the 4th channel is an alpha
        channel and it will not be quantized.

    dtype support::

        if (image size <= max_size)::

            minimum of (
                ``imgaug.augmenters.color.ChangeColorspace``,
                :func:`imgaug.augmenters.color.quantize_colors_kmeans`
            )

        if (image size > max_size)::

            minimum of (
                ``imgaug.augmenters.color.ChangeColorspace``,
                :func:`imgaug.augmenters.color.quantize_colors_kmeans`,
                :func:`imgaug.imgaug.imresize_single_image`
            )

    Parameters
    ----------
    n_colors : int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        Target number of colors in the generated output image.
        This corresponds to the number of clusters in k-Means, i.e. ``k``.
        Sampled values below ``2`` will always be clipped to ``2``.

            * If a number, exactly that value will always be used.
            * If a tuple ``(a, b)``, then a value from the discrete
              interval ``[a..b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a ``StochasticParameter``, then a value will be sampled per
              image from that parameter.

    to_colorspace : None or str or list of str or imgaug.parameters.StochasticParameter
        The colorspace in which to perform the quantization.
        See :func:`imgaug.augmenters.color.change_colorspace_` for valid values.
        This will be ignored for grayscale input images.

            * If ``None`` the colorspace of input images will not be changed.
            * If a string, it must be among the allowed colorspaces.
            * If a list, it is expected to be a list of strings, each one
              being an allowed colorspace. A random element from the list
              will be chosen per image.
            * If a StochasticParameter, it is expected to return string. A new
              sample will be drawn per image.

    from_colorspace : str, optional
        The colorspace of the input images.
        See `to_colorspace`. Only a single string is allowed.

    max_size : int or None, optional
        Maximum image size at which to perform the augmentation.
        If the width or height of an image exceeds this value, it will be
        downscaled before running the augmentation so that the longest side
        matches `max_size`.
        This is done to speed up the augmentation. The final output image has
        the same size as the input image. Use ``None`` to apply no downscaling.

    interpolation : int or str, optional
        Interpolation method to use during downscaling when `max_size` is
        exceeded. Valid methods are the same as in
        :func:`imgaug.imgaug.imresize_single_image`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.KMeansColorQuantization()

    Create an augmenter to apply k-Means color quantization to images using a
    random amount of colors, sampled uniformly from the interval ``[2..16]``.
    It assumes the input image colorspace to be ``RGB`` and clusters colors
    randomly in ``RGB`` or ``Lab`` colorspace.

    >>> aug = iaa.KMeansColorQuantization(n_colors=8)

    Create an augmenter that quantizes images to (up to) eight colors.

    >>> aug = iaa.KMeansColorQuantization(n_colors=(4, 16))

    Create an augmenter that quantizes images to (up to) ``n`` colors,
    where ``n`` is randomly and uniformly sampled from the discrete interval
    ``[4..16]``.

    >>> aug = iaa.KMeansColorQuantization(
    >>>     from_colorspace=iaa.CSPACE_BGR)

    Create an augmenter that quantizes input images that are in
    ``BGR`` colorspace. The quantization happens in ``RGB`` or ``Lab``
    colorspace, into which the images are temporarily converted.

    >>> aug = iaa.KMeansColorQuantization(
    >>>     to_colorspace=[iaa.CSPACE_RGB, iaa.CSPACE_HSV])

    Create an augmenter that quantizes images by clustering colors randomly
    in either ``RGB`` or ``HSV`` colorspace. The assumed input colorspace
    of images is ``RGB``.

    """

    def __init__(self, n_colors=(2, 16), from_colorspace=CSPACE_RGB,
                 to_colorspace=[CSPACE_RGB, CSPACE_Lab],
                 max_size=128, interpolation="linear",
                 name=None, deterministic=False, random_state=None):
        # pylint: disable=dangerous-default-value
        super(KMeansColorQuantization, self).__init__(
            n_colors=n_colors,
            from_colorspace=from_colorspace,
            to_colorspace=to_colorspace,
            max_size=max_size,
            interpolation=interpolation,
            name=name, deterministic=deterministic, random_state=random_state)

    def _quantize(self, image, n_colors):
        return quantize_colors_kmeans(image, n_colors)


def quantize_colors_kmeans(image, n_colors, n_max_iter=10, eps=1.0):
    """
    Apply k-Means color quantization to an image.

    Code similar to https://docs.opencv.org/3.0-beta/doc/py_tutorials/py_ml/
    py_kmeans/py_kmeans_opencv/py_kmeans_opencv.html

    dtype support::

        * ``uint8``: yes; fully tested
        * ``uint16``: no
        * ``uint32``: no
        * ``uint64``: no
        * ``int8``: no
        * ``int16``: no
        * ``int32``: no
        * ``int64``: no
        * ``float16``: no
        * ``float32``: no
        * ``float64``: no
        * ``float128``: no
        * ``bool``: no

    Parameters
    ----------
    image : ndarray
        Image in which to quantize colors. Expected to be of shape ``(H,W)``
        or ``(H,W,C)`` with ``C`` usually being ``1`` or ``3``.

    n_colors : int
        Maximum number of output colors.

    n_max_iter : int, optional
        Maximum number of iterations in k-Means.

    eps : float, optional
        Minimum change of all clusters per k-Means iteration. If all clusters
        change by less than this amount in an iteration, the clustering is
        stopped.

    Returns
    -------
    ndarray
        Image with quantized colors.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> import numpy as np
    >>> image = np.arange(4 * 4 * 3, dtype=np.uint8).reshape((4, 4, 3))
    >>> image_quantized = iaa.quantize_colors_kmeans(image, 6)

    Generates a ``4x4`` image with ``3`` channels, containing consecutive
    values from ``0`` to ``4*4*3``, leading to an equal number of colors.
    These colors are then quantized so that only ``6`` are remaining. Note
    that the six remaining colors do have to appear in the input image.

    """
    assert image.ndim in [2, 3], (
        "Expected two- or three-dimensional image shape, "
        "got shape %s." % (image.shape,))
    assert image.dtype.name == "uint8", "Expected uint8 image, got %s." % (
        image.dtype.name,)
    assert 2 <= n_colors <= 256, (
        "Expected n_colors to be in the discrete interval [2..256]. "
        "Got a value of %d instead." % (n_colors,))

    # without this check, kmeans throws an exception
    n_pixels = np.prod(image.shape[0:2])
    if n_colors >= n_pixels:
        return np.copy(image)

    nb_channels = 1 if image.ndim == 2 else image.shape[-1]
    colors = image.reshape((-1, nb_channels)).astype(np.float32)

    criteria = (cv2.TERM_CRITERIA_MAX_ITER + cv2.TERM_CRITERIA_EPS,
                n_max_iter, eps)
    attempts = 1

    # We want our quantization function to be deterministic (so that the
    # augmenter using it can also be executed deterministically). Hence we
    # set the RGN seed here.
    # This is fairly ugly, but in cv2 there seems to be no other way to
    # achieve determinism. Using cv2.KMEANS_PP_CENTERS does not help, as it
    # is non-deterministic (tested). In C++ the function has an rgn argument,
    # but not in python. In python there also seems to be no way to read out
    # cv2's RNG state, so we can't set it back after executing this function.
    # TODO this is quite hacky
    cv2.setRNGSeed(1)
    _compactness, labels, centers = cv2.kmeans(
        colors, n_colors, None, criteria, attempts, cv2.KMEANS_RANDOM_CENTERS)
    # TODO replace by sample_seed function
    # cv2 seems to be able to handle SEED_MAX_VALUE (tested) but not floats
    cv2.setRNGSeed(iarandom.get_global_rng().generate_seed_())

    # Convert back to uint8 (or whatever the image dtype was) and to input
    # image shape
    centers_uint8 = np.array(centers, dtype=image.dtype)
    quantized_flat = centers_uint8[labels.flatten()]
    return quantized_flat.reshape(image.shape)


class UniformColorQuantization(_AbstractColorQuantization):
    """Quantize colors into N bins with regular distance.

    For ``uint8`` images the equation is ``floor(v/q)*q + q/2`` with
    ``q = 256/N``, where ``v`` is a pixel intensity value and ``N`` is
    the target number of colors after quantization.

    This augmenter is faster than ``KMeansColorQuantization``, but the
    set of possible output colors is constant (i.e. independent of the
    input images). It may produce unsatisfying outputs for input images
    that are made up of very similar colors.

    .. note::

        This augmenter expects input images to be either grayscale
        or to have 3 or 4 channels and use colorspace `from_colorspace`. If
        images have 4 channels, it is assumed that the 4th channel is an alpha
        channel and it will not be quantized.

    dtype support::

        if (image size <= max_size)::

            minimum of (
                ``imgaug.augmenters.color.ChangeColorspace``,
                :func:`imgaug.augmenters.color.quantize_colors_uniform`
            )

        if (image size > max_size)::

            minimum of (
                ``imgaug.augmenters.color.ChangeColorspace``,
                :func:`imgaug.augmenters.color.quantize_colors_uniform`,
                :func:`imgaug.imgaug.imresize_single_image`
            )

    Parameters
    ----------
    n_colors : int or tuple of int or list of int or imgaug.parameters.StochasticParameter, optional
        Target number of colors to use in the generated output image.

            * If a number, exactly that value will always be used.
            * If a tuple ``(a, b)``, then a value from the discrete
              interval ``[a..b]`` will be sampled per image.
            * If a list, then a random value will be sampled from that list
              per image.
            * If a ``StochasticParameter``, then a value will be sampled per
              image from that parameter.

    to_colorspace : None or str or list of str or imgaug.parameters.StochasticParameter
        The colorspace in which to perform the quantization.
        See :func:`imgaug.augmenters.color.change_colorspace_` for valid values.
        This will be ignored for grayscale input images.

            * If ``None`` the colorspace of input images will not be changed.
            * If a string, it must be among the allowed colorspaces.
            * If a list, it is expected to be a list of strings, each one
              being an allowed colorspace. A random element from the list
              will be chosen per image.
            * If a StochasticParameter, it is expected to return string. A new
              sample will be drawn per image.

    from_colorspace : str, optional
        The colorspace of the input images.
        See `to_colorspace`. Only a single string is allowed.

    max_size : None or int, optional
        Maximum image size at which to perform the augmentation.
        If the width or height of an image exceeds this value, it will be
        downscaled before running the augmentation so that the longest side
        matches `max_size`.
        This is done to speed up the augmentation. The final output image has
        the same size as the input image. Use ``None`` to apply no downscaling.

    interpolation : int or str, optional
        Interpolation method to use during downscaling when `max_size` is
        exceeded. Valid methods are the same as in
        :func:`imgaug.imgaug.imresize_single_image`.

    name : None or str, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    deterministic : bool, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    random_state : None or int or imgaug.random.RNG or numpy.random.Generator or numpy.random.bit_generator.BitGenerator or numpy.random.SeedSequence or numpy.random.RandomState, optional
        See :func:`imgaug.augmenters.meta.Augmenter.__init__`.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> aug = iaa.UniformColorQuantization()

    Create an augmenter to apply uniform color quantization to images using a
    random amount of colors, sampled uniformly from the discrete interval
    ``[2..16]``.

    >>> aug = iaa.UniformColorQuantization(n_colors=8)

    Create an augmenter that quantizes images to (up to) eight colors.

    >>> aug = iaa.UniformColorQuantization(n_colors=(4, 16))

    Create an augmenter that quantizes images to (up to) ``n`` colors,
    where ``n`` is randomly and uniformly sampled from the discrete interval
    ``[4..16]``.

    >>> aug = iaa.UniformColorQuantization(
    >>>     from_colorspace=iaa.CSPACE_BGR,
    >>>     to_colorspace=[iaa.CSPACE_RGB, iaa.CSPACE_HSV])

    Create an augmenter that uniformly quantizes images in either ``RGB``
    or ``HSV`` colorspace (randomly picked per image). The input colorspace
    of all images has to be ``BGR``.

    """

    def __init__(self,
                 n_colors=(2, 16),
                 from_colorspace=CSPACE_RGB,
                 to_colorspace=None,
                 max_size=None,
                 interpolation="linear",
                 name=None, deterministic=False, random_state=None):
        # pylint: disable=dangerous-default-value
        super(UniformColorQuantization, self).__init__(
            n_colors=n_colors,
            from_colorspace=from_colorspace,
            to_colorspace=to_colorspace,
            max_size=max_size,
            interpolation=interpolation,
            name=name, deterministic=deterministic, random_state=random_state)

    def _quantize(self, image, n_colors):
        return quantize_colors_uniform(image, n_colors)


def quantize_colors_uniform(image, n_colors):
    """Quantize colors into N bins with regular distance.

    For ``uint8`` images the equation is ``floor(v/q)*q + q/2`` with
    ``q = 256/N``, where ``v`` is a pixel intensity value and ``N`` is
    the target number of colors after quantization.

    dtype support::

        * ``uint8``: yes; fully tested
        * ``uint16``: no
        * ``uint32``: no
        * ``uint64``: no
        * ``int8``: no
        * ``int16``: no
        * ``int32``: no
        * ``int64``: no
        * ``float16``: no
        * ``float32``: no
        * ``float64``: no
        * ``float128``: no
        * ``bool``: no

    Parameters
    ----------
    image : ndarray
        Image in which to quantize colors. Expected to be of shape ``(H,W)``
        or ``(H,W,C)`` with ``C`` usually being ``1`` or ``3``.

    n_colors : int
        Maximum number of output colors.

    Returns
    -------
    ndarray
        Image with quantized colors.

    Examples
    --------
    >>> import imgaug.augmenters as iaa
    >>> import numpy as np
    >>> image = np.arange(4 * 4 * 3, dtype=np.uint8).reshape((4, 4, 3))
    >>> image_quantized = iaa.quantize_colors_uniform(image, 6)

    Generates a ``4x4`` image with ``3`` channels, containing consecutive
    values from ``0`` to ``4*4*3``, leading to an equal number of colors.
    These colors are then quantized so that only ``6`` are remaining. Note
    that the six remaining colors do have to appear in the input image.

    """
    assert image.dtype.name == "uint8", "Expected uint8 image, got %s." % (
        image.dtype.name,)
    assert 2 <= n_colors <= 256, (
        "Expected n_colors to be in the discrete interval [2..256]. "
        "Got a value of %d instead." % (n_colors,))

    n_colors = np.clip(n_colors, 2, 256)

    if n_colors == 256:
        return np.copy(image)

    q = 256 / n_colors
    image_aug = np.floor(image.astype(np.float32) / q) * q + q/2

    image_aug_uint8 = np.clip(np.round(image_aug), 0, 255).astype(np.uint8)
    return image_aug_uint8