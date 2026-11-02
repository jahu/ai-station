/* Developer qualification only: create/destroy one empty owned VM. No guest,
 * vCPU, disk, network, Docker install, root or consumer capability is enabled. */
#include <Hypervisor/Hypervisor.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/sysctl.h>
#include <unistd.h>

#if defined(__arm64__)
#define PROBE_ARCH "arm64"
#elif defined(__x86_64__)
#define PROBE_ARCH "x86_64"
#else
#error Unsupported native qualification architecture
#endif

static void print_observation(const char *name) {
    int value = 0;
    size_t length = sizeof(value);
    if (sysctlbyname(name, &value, &length, NULL, 0) == 0 && length == sizeof(value)) {
        printf("%d", value);
    } else {
        printf("null");
    }
}

int main(void) {
    if (getuid() == 0 || geteuid() != getuid()) {
        fputs("Run this developer probe as an ordinary user.\n", stderr);
        return 2;
    }
    /* ARM takes an optional configuration object; Intel takes default flags. */
#if defined(__arm64__)
    hv_return_t created = hv_vm_create(NULL);
#else
    hv_return_t created = hv_vm_create(HV_VM_DEFAULT);
#endif
    hv_return_t destroyed = HV_SUCCESS;
    if (created == HV_SUCCESS) {
        destroyed = hv_vm_destroy();
    }
    printf("{\"schema\":1,\"architecture\":\"" PROBE_ARCH "\",\"kern.hv_support\":");
    print_observation("kern.hv_support");
    printf(",\"kern.hv_vmm_present\":");
    print_observation("kern.hv_vmm_present");
    printf(",\"create_return\":%u,\"destroy_return\":", (unsigned)(uint32_t)created);
    if (created == HV_SUCCESS) {
        printf("%u", (unsigned)(uint32_t)destroyed);
    } else {
        printf("null");
    }
    printf(",\"empty_vm_created\":%s,\"empty_vm_destroyed\":%s,"
           "\"DockerDesktop_tested\":false,\"consumer_installer_qualified\":false}\n",
           created == HV_SUCCESS ? "true" : "false",
           created == HV_SUCCESS && destroyed == HV_SUCCESS ? "true" : "false");
    /* Unavailable virtualization is an observation, not passing Docker support.
     * A VM we created but could not destroy is an actual failed experiment. */
    return created == HV_SUCCESS && destroyed != HV_SUCCESS ? 1 : 0;
}
