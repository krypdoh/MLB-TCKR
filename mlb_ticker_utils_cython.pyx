# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True, nonecheck=False
"""
Cython-optimized utilities for MLB ticker smooth scrolling and rendering.

Build with: python setup_mlb_cython.py build_ext --inplace
"""

import numpy as np
cimport numpy as np
from libc.math cimport fmod, floor

# Required when cimporting numpy — initialises the C-level numpy API.
np.import_array()

DTYPE_F32 = np.float32
DTYPE_I32 = np.int32

CYTHON_AVAILABLE = True
print("[MLB-PERF] Cython MLB ticker utils loaded - smooth scrolling enabled")


# ---------------------------------------------------------------------------
# Scrolling optimization functions
# ---------------------------------------------------------------------------

cpdef double calculate_smooth_scroll(double current_offset, double speed, double max_width):
    """
    Calculate smooth scroll position with sub-pixel accuracy.
    
    Args:
        current_offset: Current scroll offset (float)
        speed: Scroll speed per frame
        max_width: Maximum width before reset (usually half of ticker pixmap width)
    
    Returns:
        New scroll offset
    """
    cdef double new_offset = current_offset + speed
    
    # Reset to 0 when we've scrolled past the halfway point
    if new_offset >= max_width:
        new_offset = 0.0
    
    return new_offset


cpdef int get_pixel_position(double float_offset):
    """
    Convert floating-point scroll offset to integer pixel position.
    Uses floor for consistent rounding.
    """
    return <int>floor(float_offset)


cpdef double adjust_speed_for_framerate(double base_speed, int target_fps, int base_fps=30):
    """
    Adjust scroll speed when changing frame rates to maintain same visual speed.
    
    Args:
        base_speed: Original speed at base_fps
        target_fps: New target frame rate
        base_fps: Original frame rate
    
    Returns:
        Adjusted speed for target_fps
    """
    cdef double fps_ratio = <double>base_fps / <double>target_fps
    return base_speed * fps_ratio


# ---------------------------------------------------------------------------
# Timing and animation helpers
# ---------------------------------------------------------------------------

cpdef bint should_update_data(double elapsed_ms, double update_interval_ms):
    """
    Determine if data should be updated based on elapsed time.
    
    Args:
        elapsed_ms: Milliseconds since last update
        update_interval_ms: Update interval in milliseconds
    
    Returns:
        True if data should be updated
    """
    return elapsed_ms >= update_interval_ms


cpdef double calculate_interpolation(double start_val, double end_val, double t):
    """
    Linear interpolation between two values.
    
    Args:
        start_val: Starting value
        end_val: Ending value
        t: Interpolation factor (0.0 to 1.0)
    
    Returns:
        Interpolated value
    """
    if t <= 0.0:
        return start_val
    if t >= 1.0:
        return end_val
    return start_val + (end_val - start_val) * t


# ---------------------------------------------------------------------------
# Color and rendering helpers
# ---------------------------------------------------------------------------

cpdef tuple hex_to_rgb(str hex_color):
    """
    Convert hex color string to RGB tuple.
    
    Args:
        hex_color: Hex color string (e.g., "#FF0000")
    
    Returns:
        Tuple of (r, g, b) values (0-255)
    """
    cdef str hex_clean = hex_color.lstrip('#')
    cdef int r, g, b
    
    if len(hex_clean) == 6:
        r = int(hex_clean[0:2], 16)
        g = int(hex_clean[2:4], 16)
        b = int(hex_clean[4:6], 16)
        return (r, g, b)
    
    return (255, 255, 255)  # Default to white


cpdef int blend_alpha(int base_alpha, int overlay_alpha):
    """
    Blend two alpha values.
    
    Args:
        base_alpha: Base alpha value (0-255)
        overlay_alpha: Overlay alpha value (0-255)
    
    Returns:
        Blended alpha value (0-255)
    """
    cdef int result = base_alpha + overlay_alpha
    if result > 255:
        return 255
    return result
