# Lag-phase uncertainty algebra and simulation

This is an estimator-model check, not a radiance pilot or native/game quality
test. Let past RGB coefficients F_j=S exp(i omega j)+epsilon_j, j=0..m-1,
with independent circular complex Gaussian noise E|epsilon_j,c|²=q_j.
S is fixed complex RGB, noise independent across channels and time. C is the
pooled lag sum sum_j,c F_(j+1,c) conj(F_(j,c)). L=m-1 and E=sum_c|S_c|².

Rotating C by exp(-i omega), the first-order imaginary signal/noise sum telescopes
to Im(sum_c (eta_last,c-eta_first,c) conj(S_c)). Circular independence gives
exact imaginary variance V=E(q_first+q_last)/2+3 sum_adj(q_j q_(j-1))/2.
Linearized angle SE is sqrt(V)/|C|; its plug-in signal power and denominator are
not an exact confidence interval. Conditional phase qualification/support,
noise correlations, coefficient drift and phase acceleration are not covered.

For aligned past mean G(theta)=mean_j F_j exp(i theta (m-j)), its exact derivative
is i mean_j (m-j) F_j exp(i theta (m-j)), not generally i mean_age G(theta).
The mean_age replacement is valid on the noise-free constant-amplitude model.
A first-order Cauchy variance expression (sqrt(v_mean)+|dG/dtheta| SE_theta)^2
accounts conservatively for unknown covariance in the linearization. It is not
a finite-sample nonlinear bound; random derivative/SE estimates require care.

Fixed seed950411,16384 trials per case, batch256. m8/16/32/64, signal/noise power
ratio16/64/1000, omega0/.08, equal-q and linearly varying q(.5..1.5 meanq).
Check empirical exact imaginary variance relative error<=.06 for these48 IID
cases; Monte Carlo tolerance is engineering verification, not confidence proof.
Record empirical angle variance, true-linearized and plug-in SE, null3SE
selection fraction, predicted mean MSE and nominal first-order upper separately.
Central-difference derivative delta1e-6 must match exact weighted-age derivative
to relative error1e-7. Colored-channel and temporal-AR noise are descriptive
counterexamples only: their discrepancy must remain visible, not be gated away.
Oracle model S/omega/q are used only to validate algebra, not as a pilot input.
