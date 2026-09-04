// Empirically probes precision/data-type support on real AMD hardware, at
// the HIP C++ compiler/type level: a closer match to what ROCm's own
// precision-support.rst actually measures ("HIP C++ Type implementation
// support") than the companion PyTorch-based script in this directory,
// which instead measures a specific ML framework's operator/kernel
// coverage. Both are useful; neither replaces the other. See this
// directory's README for how to read results from each side by side.
//
// Every catalog precision_support key maps to a real HIP C++ type (the
// same tokens ingest_rocm_precision_support.py's _TYPE_KEY_MAP uses), and
// every one of those types exposes an explicit T(float) constructor plus
// an explicit operator float() conversion, so one generic template
// covers all 15 types: construct from float on-device, convert back,
// add, and check the result.
//
// KNOWN LIMITATION: some HIP headers (amd_hip_fp8.h) gate certain fp8
// variants as host-only (not device-callable) depending on the *target*
// GPU architecture being compiled for (see HIP_FP8_TYPE_FNUZ/
// HIP_FP8_TYPE_OCP in that header), but only during the device
// compilation pass; during the host pass both are unconditionally
// enabled, so this can't be detected from host code in main(). This file
// assumes every fp8 variant is device-usable, true for gfx1151 (Strix
// Halo, confirmed by inspection: neither the gfx942-only nor the
// gfx1200/1201/950/1250-only branch applies, so it falls into the
// "both enabled" default) and for pre-gfx9/RDNA1/RDNA2-class generic
// targets. Compiling this for a target where one fp8 family is
// host-only (e.g. gfx942/MI300, where OCP e4m3/e5m2 are host-only) will
// fail to compile with a clear, specific error naming the offending
// constructor: a real, honest signal, just a compile failure rather
// than a clean per-type result. Extend with per-type preprocessor guards
// if/when this needs to run on that class of hardware.
//
// Build and run (requires hipcc + a real AMD GPU; not part of this
// project's own CI or uv-managed dependencies):
//
//     hipcc --offload-arch=native -O2 -o /tmp/validate_precision_support_hip \
//         tools/hardware_validation/validate_precision_support_hip.cpp
//     /tmp/validate_precision_support_hip
//
// or just run validate_precision_support_hip.sh, which does both steps.

#include <hip/hip_bfloat16.h>
#include <hip/hip_fp16.h>
#include <hip/hip_fp4.h>
#include <hip/hip_fp6.h>
#include <hip/hip_fp8.h>
#include <hip/hip_runtime.h>

#include <cmath>
#include <cstdint>
#include <cstdio>

template <typename T>
__global__ void roundtrip_kernel(float a, float b, float* out) {
  T ta(a);
  T tb(b);
  out[0] = float(ta) + float(tb);
}

// Returns true iff the type compiled, launched, ran, and produced a
// result within `tol` of `expected`, not just "did it not crash".
template <typename T>
bool run_probe(const char* catalog_key, float a, float b, float expected, float tol) {
  float* d_out = nullptr;
  if (hipMalloc(&d_out, sizeof(float)) != hipSuccess) {
    std::printf("  %-16s FAIL    hipMalloc failed\n", catalog_key);
    return false;
  }

  hipLaunchKernelGGL((roundtrip_kernel<T>), dim3(1), dim3(1), 0, 0, a, b, d_out);
  hipError_t launch_err = hipGetLastError();
  if (launch_err != hipSuccess) {
    std::printf("  %-16s FAIL    kernel launch: %s\n", catalog_key, hipGetErrorString(launch_err));
    (void)hipFree(d_out);
    return false;
  }

  hipError_t sync_err = hipDeviceSynchronize();
  if (sync_err != hipSuccess) {
    std::printf("  %-16s FAIL    device execution: %s\n", catalog_key, hipGetErrorString(sync_err));
    (void)hipFree(d_out);
    return false;
  }

  float h_out = 0.0f;
  (void)hipMemcpy(&h_out, d_out, sizeof(float), hipMemcpyDeviceToHost);
  (void)hipFree(d_out);

  bool finite = std::isfinite(h_out);
  bool close_enough = finite && std::fabs(h_out - expected) <= tol;
  std::printf(
      "  %-16s %-7s got=%.4f expected=%.4f (tol %.4f)\n", catalog_key, close_enough ? "PASS" : "FAIL", h_out,
      expected, tol
  );
  return close_enough;
}

int main() {
  hipDeviceProp_t props{};
  if (hipGetDeviceProperties(&props, 0) != hipSuccess) {
    std::fprintf(stderr, "No GPU visible to HIP. Nothing to probe.\n");
    return 1;
  }
  std::printf("Device: %s (%s)\n", props.name, props.gcnArchName);
  std::printf(
      "Testing: on-device construct-from-float + convert-back-to-float roundtrip via a real HIP\n"
      "kernel, per precision_support type. This matches ROCm's own 'HIP C++ Type' framing directly,\n"
      "rather than a specific ML framework's operator/kernel coverage.\n\n"
  );

  int failures = 0;

  // Wide/arithmetic types: exact roundtrip expected, tight tolerance.
  if (!run_probe<int8_t>("int8", 3, 4, 7, 0.0f)) failures++;
  if (!run_probe<int16_t>("int16", 3, 4, 7, 0.0f)) failures++;
  if (!run_probe<int32_t>("int32", 3, 4, 7, 0.0f)) failures++;
  if (!run_probe<int64_t>("int64", 3, 4, 7, 0.0f)) failures++;
  if (!run_probe<__half>("float16", 3, 4, 7, 0.01f)) failures++;
  if (!run_probe<hip_bfloat16>("bfloat16", 3, 4, 7, 0.1f)) failures++;
  if (!run_probe<float>("float32", 3, 4, 7, 1e-5f)) failures++;
  if (!run_probe<double>("float64", 3, 4, 7, 1e-9f)) failures++;

  // Narrow float types: quantization error is expected and correct
  // behavior, not a failure. Tolerances are generous on purpose.
  if (!run_probe<__hip_fp8_e4m3>("fp8_e4m3", 3, 4, 7, 1.5f)) failures++;
  if (!run_probe<__hip_fp8_e5m2>("fp8_e5m2", 3, 4, 7, 2.0f)) failures++;
  if (!run_probe<__hip_fp8_e4m3_fnuz>("fp8_e4m3_fnuz", 3, 4, 7, 1.5f)) failures++;
  if (!run_probe<__hip_fp8_e5m2_fnuz>("fp8_e5m2_fnuz", 3, 4, 7, 2.0f)) failures++;
  if (!run_probe<__hip_fp4_e2m1>("fp4_e2m1", 3, 4, 7, 3.0f)) failures++;
  if (!run_probe<__hip_fp6_e2m3>("fp6_e2m3", 3, 4, 7, 1.0f)) failures++;
  if (!run_probe<__hip_fp6_e3m2>("fp6_e3m2", 3, 4, 7, 1.5f)) failures++;

  std::printf("\n%d/15 types passed the on-device construct+convert roundtrip.\n", 15 - failures);
  std::printf(
      "This is diagnostic output for a human to review, not an automatic source. A type passing\n"
      "here means it's usable on-device on this target, not that it's fast (this doesn't exercise\n"
      "accelerated matrix-core throughput at all). See catalog/notes.json / PRD section 6.5 /\n"
      "CONTRIBUTING.md before turning this into a hand-authored note; this program never writes to\n"
      "notes.json itself.\n"
  );

  return failures == 0 ? 0 : 1;
}
