// D02/WP08 experiment artifact: the surface-valid checkerboard fill variant of
// the production decode. Same source, only the eligibility gate enabled. It is
// dispatched only behind its config key after live selector/phase evidence
// arrives; the production FSRDNrdRawPrePassDecode artifact stays the default.
#define FSRD_NRD_SURFACE_VALID_FILL 1
#include "FSRDNrdRawPrePassDecode.hlsl"
