# NRD Bridge motion stability guard

Scope: guard nonfinite previous stability and negative motion magnitudes. No defaults changed.

Run: `g++ -std=c++20 -Wall -Wextra -Werror -I. tests/motion_stability_guard.cpp -o /tmp/motion_stability_guard && /tmp/motion_stability_guard`.

This is a partial fix, NOT the complete previously discussed audit patchset. Windows/MSVC, GPU and game validation are pending.
