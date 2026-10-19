"""Own-observation features available before an acquisition decision."""

from phdsim.probability import binary_entropy

QUALITY_NAMES = ('brightness', 'contrast', 'dark_fraction', 'bright_fraction',
                 'horizontal_gradient', 'vertical_gradient', 'top_brightness', 'bottom_brightness')
CONFIDENCE_NAMES = ('own_probability', 'own_probability_squared', 'own_entropy')


def acquisition_features(evidence, include_quality):
    p = evidence.probability
    values = (p, p * p, binary_entropy(p))
    if include_quality:
        if len(evidence.local_features) != len(QUALITY_NAMES):
            raise ValueError('Image quality features are missing')
        values += evidence.local_features
    return values
