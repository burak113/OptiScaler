"""Post-observation diagnostic retention rule; never an image-quality criterion."""
import hashlib
KNOWN_WARNING=b'SDK: Frame index jump detected. Resetting...\r\n'
def evaluate(case,counts,stderr):
    assert len(counts)==8
    assert counts[3:6]==[0,0,0],'D3D12 errors/warnings or SDK errors'
    warning_count=counts[6];no_api=case['no_api_frame']==24
    if no_api:
        assert warning_count in(0,1),'noAPI SDK warning count outside0or1'
        assert stderr==(KNOWN_WARNING if warning_count==1 else b''),'SDK warning bytes outside exact known allowlist'
    else:
        assert warning_count==0 and stderr==b'','record-discard requires no SDK warnings/messages'
    return{'schema':'post-observation-exact-diagnostic-warning-admissibility-v2','diagnostic_retention_admissible':True,
        'no_API_arm':no_api,'actual_SDK_warning_count':warning_count,'stderr_bytes':len(stderr),'stderr_sha256':hashlib.sha256(stderr).hexdigest(),
        'known_warning_present':warning_count==1,'warning_count_is_quality_score':False,'quality_accepted':False,
        'qualification':'Post-observation retention amendment allows noAPI0or1 only this exactSDKwarning. It retains actual warning counts; absence in explicitRESET arms is admissible. It establishes no universal automatic RESET contract or image-quality pass.'}
