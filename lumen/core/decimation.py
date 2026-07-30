"""
Lumen Circuit Studio — High-Performance Waveform Decimation Engine

Implements LTTB (Largest-Triangle-Three-Buckets) downsampling to enable
smooth 60 FPS viewport rendering of multi-million point RAW simulation files
without freezing or hanging the Qt GUI.
"""
from __future__ import annotations

import math
from typing import List, Tuple


def lttb_decimate(x_data: List[float], y_data: List[float], target_points: int = 2000) -> Tuple[List[float], List[float]]:
    """
    Downsample (x_data, y_data) to target_points using Largest-Triangle-Three-Buckets (LTTB).
    Returns (downsampled_x, downsampled_y).
    """
    n = len(x_data)
    if n <= target_points or target_points < 3:
        return list(x_data), list(y_data)

    sampled_x = [x_data[0]]
    sampled_y = [y_data[0]]

    # Bucket size for remaining data excluding first and last
    every = (n - 2) / (target_points - 2)
    a = 0  # First point

    for i in range(0, target_points - 2):
        # Calculate point average for next bucket (c)
        avg_x = 0.0
        avg_y = 0.0
        avg_range_start = int(math.floor((i + 1) * every)) + 1
        avg_range_end = int(math.floor((i + 2) * every)) + 1
        avg_range_end = min(avg_range_end, n)

        avg_range_length = avg_range_end - avg_range_start
        if avg_range_length > 0:
            for j in range(avg_range_start, avg_range_end):
                avg_x += x_data[j]
                avg_y += y_data[j]
            avg_x /= avg_range_length
            avg_y /= avg_range_length
        else:
            avg_x = x_data[min(avg_range_start, n - 1)]
            avg_y = y_data[min(avg_range_start, n - 1)]

        # Get the range for current bucket (b)
        range_offs = int(math.floor((i + 0) * every)) + 1
        range_to = int(math.floor((i + 1) * every)) + 1

        # Point a
        point_a_x = x_data[a]
        point_a_y = y_data[a]

        max_area = -1.0
        max_area_point = range_offs

        for j in range(range_offs, min(range_to, n)):
            # Calculate triangle area over points (a, j, avg)
            area = abs(
                (point_a_x - avg_x) * (y_data[j] - point_a_y) -
                (point_a_x - x_data[j]) * (avg_y - point_a_y)
            ) * 0.5

            if area > max_area:
                max_area = area
                max_area_point = j

        sampled_x.append(x_data[max_area_point])
        sampled_y.append(y_data[max_area_point])
        a = max_area_point  # Next a is current selected point

    # Always include last point
    sampled_x.append(x_data[-1])
    sampled_y.append(y_data[-1])

    return sampled_x, sampled_y
