"""Planar geometry for inferred chair-to-table associations."""
import math


def forward_table_distance(points, position, yaw):
    """Distance along a chair's forward ray to the table's convex footprint.

    A table center is not a facing target for every chair along a long table.
    This association uses the whole footprint; collision validation is separate.
    """
    vertices = sorted({(float(p[0]), float(p[1])) for p in points})
    if len(vertices) < 3:
        return None
    def cross(a, b):
        return a[0]*b[1]-a[1]*b[0]
    def subtract(a, b):
        return a[0]-b[0], a[1]-b[1]
    def chain(sequence):
        result = []
        for point in sequence:
            while len(result) > 1 and cross(subtract(result[-1], result[-2]), subtract(point, result[-1])) <= 0:
                result.pop()
            result.append(point)
        return result
    hull = chain(vertices)[:-1]+chain(reversed(vertices))[:-1]
    if len(hull) < 3:
        return None
    front = math.sin(yaw), -math.cos(yaw)
    lower, upper = 0., math.inf
    for a, b in zip(hull, hull[1:]+hull[:1]):
        edge = subtract(b, a)
        base, rate = cross(edge, subtract(position, a)), cross(edge, front)
        if abs(rate) < 1e-10:
            if base < -1e-8:
                return None
        elif rate > 0:
            lower = max(lower, -base/rate)
        else:
            upper = min(upper, -base/rate)
    return lower if lower <= upper+1e-8 else None
