"""Features of two probabilities available only after both observations arrive."""

from phdsim.probability import logit

FUSION_NAMES = ('rgb_logit', 'thermal_logit', 'logit_product', 'absolute_logit_difference')


def fusion_features(rgb_probability, thermal_probability):
    rgb, thermal = logit(rgb_probability), logit(thermal_probability)
    return (rgb, thermal, rgb * thermal, abs(rgb - thermal))
