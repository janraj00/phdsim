"""Rest-to-rest approximation of the PX4 v1.16.0 X500 mission trajectory."""

from dataclasses import dataclass
from math import ceil, hypot, sqrt


MODEL_ID = "px4-v1.16.0-gz_x500"
SECONDS_PER_TICK = 1.0
_CRUISE_XY_M_S = 5.0
_ASCENT_M_S = 3.0
_DESCENT_M_S = 1.5
_ACCEL_XY_M_S2 = 3.0
# Use the lower of the upward and downward limits for both halves of the
# symmetric profile, so both acceleration and braking stay within them.
_ACCEL_Z_M_S2 = min(4.0, 3.0)
_JERK_M_S3 = 4.0


@dataclass(frozen=True)
class FlightProfile:
    distance_m: float
    jerk_m_s3: float
    ramp_s: float
    acceleration_hold_s: float
    cruise_s: float

    @property
    def duration_s(self) -> float:
        return 4 * self.ramp_s + 2 * self.acceleration_hold_s + self.cruise_s

    @property
    def travel_ticks(self) -> int:
        return ceil(self.duration_s / SECONDS_PER_TICK)

    def progress_at(self, seconds: float) -> float:
        """Distance along the straight flight leg, as a fraction of its length."""
        if seconds >= self.duration_s:
            return 1.0
        if seconds <= 0:
            return 0.0
        ramp, hold, jerk = self.ramp_s, self.acceleration_hold_s, self.jerk_m_s3
        phases = ((ramp, jerk), (hold, 0.0), (ramp, -jerk), (self.cruise_s, 0.0),
                  (ramp, -jerk), (hold, 0.0), (ramp, jerk))
        position = speed = acceleration = 0.0
        for duration, phase_jerk in phases:
            elapsed = min(seconds, duration)
            position += speed * elapsed + acceleration * elapsed**2 / 2 + phase_jerk * elapsed**3 / 6
            if seconds <= duration:
                return position / self.distance_m
            speed += acceleration * elapsed + phase_jerk * elapsed**2 / 2
            acceleration += phase_jerk * elapsed
            seconds -= duration
        return 1.0


def x500_flight(horizontal_m: float, climb_m: float = 0.0) -> FlightProfile:
    """Project PX4 limits along a straight 3D leg, then fit a symmetric S-curve."""
    distance = hypot(horizontal_m, climb_m)
    if distance == 0:
        return FlightProfile(0.0, _JERK_M_S3, 0.0, 0.0, 0.0)

    vertical_m = abs(climb_m)
    vertical_speed = _ASCENT_M_S if climb_m > 0 else _DESCENT_M_S
    speed = distance / max(horizontal_m / _CRUISE_XY_M_S, vertical_m / vertical_speed)
    acceleration = distance / max(horizontal_m / _ACCEL_XY_M_S2, vertical_m / _ACCEL_Z_M_S2)
    jerk = _JERK_M_S3 * distance / max(horizontal_m, vertical_m)

    # Find the phases needed to reach the speed cap and stop again.
    ramp = min(acceleration / jerk, sqrt(speed / jerk))
    hold = max(0.0, speed / (jerk * ramp) - ramp)
    distance_at_speed_cap = speed * (2 * ramp + hold)
    if distance >= distance_at_speed_cap:
        return FlightProfile(distance, jerk, ramp, hold, (distance - distance_at_speed_cap) / speed)

    # Short legs have no cruise phase. Solve for the lower peak speed.
    short_ramp = (distance / (2 * jerk)) ** (1 / 3)
    if short_ramp <= ramp:
        return FlightProfile(distance, jerk, short_ramp, 0.0, 0.0)
    hold = (sqrt(ramp**2 + 4 * distance / acceleration) - 3 * ramp) / 2
    return FlightProfile(distance, jerk, ramp, hold, 0.0)


def x500_level_travel_ticks(horizontal_m: float) -> int:
    return x500_flight(horizontal_m).travel_ticks
