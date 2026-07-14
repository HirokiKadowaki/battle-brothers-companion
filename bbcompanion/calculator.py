from dataclasses import dataclass, field

from .data_loader import STATS, load_archetypes, load_backgrounds, load_talents

CLOSE_MARGIN_RATIO = 0.08
CLOSE_MARGIN_MIN = 5

# 0-10 build-fit rating tuning.
# A stat that exactly meets its threshold scores THRESHOLD_SATISFACTION; hitting
# the "ideal" value (or HEADROOM_TARGET_RATIO x threshold when no ideal is given)
# scores a full 1.0; falling SHORTFALL_ZERO_FRAC below the threshold scores 0.
HEADROOM_TARGET_RATIO = 1.15
THRESHOLD_SATISFACTION = 0.7
SHORTFALL_ZERO_FRAC = 0.20
# Weight by the stat's rank in the archetype's requirement order (primary stat
# first). Primary highest, then decaying, floored at a flat baseline.
PRIMARY_WEIGHT = 3.0
WEIGHT_STEP = 0.7
BASELINE_WEIGHT = 1.0


def _stat_satisfaction(value: float, min_v: float, ideal) -> float:
    """Return how well `value` satisfies a requirement, in [0, 1]."""
    target = ideal if ideal is not None else min_v * HEADROOM_TARGET_RATIO
    if value >= target:
        return 1.0
    if value >= min_v:
        if target <= min_v:
            return 1.0
        return THRESHOLD_SATISFACTION + (1.0 - THRESHOLD_SATISFACTION) * (value - min_v) / (target - min_v)
    # Below the threshold: fall from THRESHOLD_SATISFACTION at min_v to 0.
    zero_at = min_v * (1 - SHORTFALL_ZERO_FRAC)
    if value <= zero_at:
        return 0.0
    return THRESHOLD_SATISFACTION * (value - zero_at) / (min_v - zero_at)


@dataclass
class StatProjection:
    stat: str
    current: int
    stars: int
    projected: int
    bg_min: int
    bg_max: int
    ceiling_pct: float  # how close `current` already is to the background's max roll


@dataclass
class ArchetypeFit:
    name: str
    verdict: str  # "good", "marginal", "poor"
    margin_score: float
    rating: float  # 0.0-10.0, weighted by stat priority
    limiting_stats: list = field(default_factory=list)
    details: list = field(default_factory=list)


class RecruitCalculator:
    def __init__(self):
        self.backgrounds = load_backgrounds()
        self.talents = load_talents()["growth_per_level"]
        self.archetypes = load_archetypes()

    def background_names(self):
        return sorted(self.backgrounds.keys())

    def evaluate_recruit(self, background: str, current_stats: dict, star_assignments: dict):
        """
        current_stats: {stat_key: int}
        star_assignments: {stat_key: int (0-3)}, only stats with stars need be present
        Returns (list[StatProjection], list[ArchetypeFit], overall_verdict: str)
        """
        bg = self.backgrounds[background]
        projections = []
        projected_values = {}

        for stat in STATS:
            current = current_stats.get(stat, 0)
            stars = star_assignments.get(stat, 0)
            avg_growth = self.talents[stat]["avg_no_star"]
            projected = current + 10 * avg_growth + stars * 5
            bg_min = bg[stat]["min"]
            bg_max = bg[stat]["max"]
            span = max(bg_max - bg_min, 1)
            ceiling_pct = round(max(0.0, min(1.0, (current - bg_min) / span)) * 100, 1)
            projections.append(
                StatProjection(
                    stat=stat,
                    current=current,
                    stars=stars,
                    projected=projected,
                    bg_min=bg_min,
                    bg_max=bg_max,
                    ceiling_pct=ceiling_pct,
                )
            )
            projected_values[stat] = projected

        fits = [self._fit_archetype(a, projected_values) for a in self.archetypes]
        fits.sort(key=lambda f: (_VERDICT_ORDER[f.verdict], -f.rating))

        if any(f.verdict == "good" for f in fits):
            overall = "recommend"
        elif any(f.verdict == "marginal" for f in fits):
            overall = "marginal"
        else:
            overall = "not_worth_it"

        return projections, fits, overall

    def _fit_archetype(self, archetype: dict, projected_values: dict) -> ArchetypeFit:
        required_margins = []
        limiting = []
        details = []
        has_fail = False
        has_close = False
        weighted_sat = 0.0
        total_weight = 0.0
        rank = 0  # position among required (non-optional) stats -> importance

        for req in archetype["requirements"]:
            stat = req["stat"]
            min_v = req["min"]
            optional = req.get("optional", False)
            value = projected_values.get(stat, 0)
            margin = value - min_v
            margin_ratio = margin / min_v if min_v else 0
            details.append(
                {"stat": stat, "value": value, "min": min_v, "margin": margin, "optional": optional}
            )

            if optional:
                continue

            required_margins.append(margin_ratio)
            close_margin = max(CLOSE_MARGIN_MIN, min_v * CLOSE_MARGIN_RATIO)
            if margin < -close_margin:
                has_fail = True
                limiting.append(stat)
            elif margin < 0:
                has_close = True
                limiting.append(stat)

            # Weighted 0-1 satisfaction: earlier (more important) stats weigh more.
            weight = max(BASELINE_WEIGHT, PRIMARY_WEIGHT - rank * WEIGHT_STEP)
            weighted_sat += weight * _stat_satisfaction(value, min_v, req.get("ideal"))
            total_weight += weight
            rank += 1

        margin_score = sum(required_margins) / len(required_margins) if required_margins else 0
        rating = round(10.0 * weighted_sat / total_weight, 1) if total_weight else 0.0

        if has_fail:
            verdict = "poor"
        elif has_close:
            verdict = "marginal"
        else:
            verdict = "good"

        return ArchetypeFit(
            name=archetype["name"],
            verdict=verdict,
            margin_score=round(margin_score, 3),
            rating=rating,
            limiting_stats=limiting,
            details=details,
        )


_VERDICT_ORDER = {"good": 0, "marginal": 1, "poor": 2}
