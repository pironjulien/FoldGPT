/* SPDX-License-Identifier: GPL-3.0-or-later
 * Exercise the real GPU timestamp query and calibrated-timestamp paths.
 * Select exactly one isolated Adreno ICD with VK_DRIVER_FILES. No window,
 * files, network, or other client state is accessed. Failures exit immediately;
 * the OS reclaims device resources without an unbounded device-idle wait. */
#define _POSIX_C_SOURCE 200809L
#include <vulkan/vulkan.h>
#include <errno.h>
#include <float.h>
#include <inttypes.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define CHECK(call) do { \
    VkResult result_ = (call); \
    if (result_ != VK_SUCCESS) { \
        fprintf(stderr, "%s failed: VkResult=%d\n", #call, result_); \
        return 1; \
    } \
} while (0)
#define REQUIRE(condition, message) do { \
    if (!(condition)) { fprintf(stderr, "%s\n", message); return 1; } \
} while (0)

struct calibration {
    uint64_t gpu;
    uint64_t cpu;
    uint64_t deviation;
};

/* KHR and EXT entry points have the same ABI. Using EXT types keeps this
 * standalone probe buildable with Ubuntu 24.04's Vulkan development headers. */
static VkResult calibrate(VkDevice device,
        PFN_vkGetCalibratedTimestampsEXT get_timestamps,
        struct calibration *sample) {
    const VkCalibratedTimestampInfoEXT domains[2] = {
        {.sType = VK_STRUCTURE_TYPE_CALIBRATED_TIMESTAMP_INFO_EXT,
         .timeDomain = VK_TIME_DOMAIN_DEVICE_EXT},
        {.sType = VK_STRUCTURE_TYPE_CALIBRATED_TIMESTAMP_INFO_EXT,
         .timeDomain = VK_TIME_DOMAIN_CLOCK_MONOTONIC_RAW_EXT},
    };
    uint64_t timestamps[2] = {0, 0};
    struct timespec host_before, host_after;
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &host_before) != 0)
        return VK_ERROR_UNKNOWN;
    VkResult result = get_timestamps(device, 2, domains, timestamps,
                                    &sample->deviation);
    if (clock_gettime(CLOCK_MONOTONIC_RAW, &host_after) != 0)
        return VK_ERROR_UNKNOWN;
    if (result == VK_SUCCESS) {
        sample->gpu = timestamps[0];
        sample->cpu = timestamps[1];
        const uint64_t before_ns = (uint64_t)host_before.tv_sec * UINT64_C(1000000000)
                                   + (uint64_t)host_before.tv_nsec;
        const uint64_t after_ns = (uint64_t)host_after.tv_sec * UINT64_C(1000000000)
                                  + (uint64_t)host_after.tv_nsec;
        if (sample->cpu < before_ns || sample->cpu > after_ns) {
            fprintf(stderr, "Calibrated CPU value is outside independent CLOCK_MONOTONIC_RAW bounds\n");
            return VK_ERROR_UNKNOWN;
        }
    }
    return result;
}

static uint64_t ticks_between(uint64_t first, uint64_t last, uint64_t mask) {
    return (last - first) & mask;
}

int main(void) {
    setvbuf(stdout, NULL, _IOLBF, 0);
    const VkApplicationInfo app = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "FoldGPT GPU timestamp verification",
        .apiVersion = VK_API_VERSION_1_1,
    };
    const VkInstanceCreateInfo instance_info = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pApplicationInfo = &app,
    };
    VkInstance instance;
    CHECK(vkCreateInstance(&instance_info, NULL, &instance));
    uint32_t count = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, NULL));
    REQUIRE(count == 1, "Expected exactly one isolated physical GPU");
    VkPhysicalDevice gpu;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, &gpu));
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceProperties(gpu, &properties);
    printf("GPU=%s type=%u vendor=0x%x device=0x%x\n",
           properties.deviceName, properties.deviceType,
           properties.vendorID, properties.deviceID);
    REQUIRE(properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU &&
            properties.vendorID == 0x5143 &&
            (strstr(properties.deviceName, "Adreno") ||
             strstr(properties.deviceName, "Turnip")),
            "Refusing to report a software or unrelated GPU as Adreno proof");

    const long double expected_period = 1000000000.0L / 19200000.0L;
    const long double period = properties.limits.timestampPeriod;
    REQUIRE(isfinite(period) && period > 0.0L &&
            fabsl(period - expected_period) <= expected_period * FLT_EPSILON,
            "timestampPeriod does not describe Adreno's 19.2 MHz counter");

    CHECK(vkEnumerateDeviceExtensionProperties(gpu, NULL, &count, NULL));
    VkExtensionProperties *extensions = calloc(count, sizeof(*extensions));
    REQUIRE(extensions != NULL, "Cannot allocate extension inventory");
    CHECK(vkEnumerateDeviceExtensionProperties(gpu, NULL, &count, extensions));
    int has_khr = 0, has_ext = 0;
    for (uint32_t i = 0; i < count; i++) {
        has_khr |= !strcmp(extensions[i].extensionName, "VK_KHR_calibrated_timestamps");
        has_ext |= !strcmp(extensions[i].extensionName, "VK_EXT_calibrated_timestamps");
    }
    free(extensions);
    REQUIRE(has_khr || has_ext, "Calibrated timestamp extension is unavailable");
    const char *extension = has_khr ? "VK_KHR_calibrated_timestamps"
                                    : "VK_EXT_calibrated_timestamps";
    PFN_vkGetPhysicalDeviceCalibrateableTimeDomainsEXT get_domains =
        (PFN_vkGetPhysicalDeviceCalibrateableTimeDomainsEXT)
        vkGetInstanceProcAddr(instance, has_khr ?
            "vkGetPhysicalDeviceCalibrateableTimeDomainsKHR" :
            "vkGetPhysicalDeviceCalibrateableTimeDomainsEXT");
    REQUIRE(get_domains != NULL, "Calibratable-domain entry point unavailable");
    CHECK(get_domains(gpu, &count, NULL));
    VkTimeDomainEXT *domains = calloc(count, sizeof(*domains));
    REQUIRE(domains != NULL, "Cannot allocate time-domain inventory");
    CHECK(get_domains(gpu, &count, domains));
    int has_device = 0, has_raw = 0;
    for (uint32_t i = 0; i < count; i++) {
        has_device |= domains[i] == VK_TIME_DOMAIN_DEVICE_EXT;
        has_raw |= domains[i] == VK_TIME_DOMAIN_CLOCK_MONOTONIC_RAW_EXT;
    }
    free(domains);
    REQUIRE(has_device && has_raw,
            "DEVICE and CLOCK_MONOTONIC_RAW are required for an unslewed frequency check");

    uint32_t family_count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, NULL);
    VkQueueFamilyProperties *families = calloc(family_count, sizeof(*families));
    REQUIRE(families != NULL, "Cannot allocate queue-family inventory");
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, families);
    uint32_t family = UINT32_MAX, valid_bits = 0;
    for (uint32_t i = 0; i < family_count; i++) {
        if (families[i].queueCount &&
            (families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) &&
            families[i].timestampValidBits) {
            family = i;
            valid_bits = families[i].timestampValidBits;
            break;
        }
    }
    free(families);
    REQUIRE(family != UINT32_MAX && valid_bits <= 64,
            "No graphics queue supports valid GPU timestamp queries");
    const uint64_t mask = valid_bits == 64 ? UINT64_MAX :
                          (UINT64_C(1) << valid_bits) - 1;
    const float priority = 1.0f;
    const VkDeviceQueueCreateInfo queue_info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = family, .queueCount = 1,
        .pQueuePriorities = &priority,
    };
    const VkDeviceCreateInfo device_info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .queueCreateInfoCount = 1, .pQueueCreateInfos = &queue_info,
        .enabledExtensionCount = 1, .ppEnabledExtensionNames = &extension,
    };
    VkDevice device;
    CHECK(vkCreateDevice(gpu, &device_info, NULL, &device));
    PFN_vkGetCalibratedTimestampsEXT get_timestamps =
        (PFN_vkGetCalibratedTimestampsEXT)vkGetDeviceProcAddr(device, has_khr ?
            "vkGetCalibratedTimestampsKHR" : "vkGetCalibratedTimestampsEXT");
    REQUIRE(get_timestamps != NULL, "Calibrated timestamp entry point unavailable");
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
    printf("extension=%s timestampPeriod=%.9Lf ns validBits=%u\n",
           extension, period, valid_bits);

    const VkQueryPoolCreateInfo query_info = {
        .sType = VK_STRUCTURE_TYPE_QUERY_POOL_CREATE_INFO,
        .queryType = VK_QUERY_TYPE_TIMESTAMP, .queryCount = 1,
    };
    VkQueryPool query_pool;
    CHECK(vkCreateQueryPool(device, &query_info, NULL, &query_pool));
    const VkCommandPoolCreateInfo pool_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
        .queueFamilyIndex = family,
    };
    VkCommandPool command_pool;
    CHECK(vkCreateCommandPool(device, &pool_info, NULL, &command_pool));
    const VkCommandBufferAllocateInfo command_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = command_pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
        .commandBufferCount = 1,
    };
    VkCommandBuffer command;
    CHECK(vkAllocateCommandBuffers(device, &command_info, &command));
    const VkCommandBufferBeginInfo begin_info = {
        .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO,
        .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT,
    };
    CHECK(vkBeginCommandBuffer(command, &begin_info));
    vkCmdResetQueryPool(command, query_pool, 0, 1);
    vkCmdWriteTimestamp(command, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, query_pool, 0);
    CHECK(vkEndCommandBuffer(command));
    const VkFenceCreateInfo fence_info = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkFence fence;
    CHECK(vkCreateFence(device, &fence_info, NULL, &fence));
    const VkSubmitInfo submit = {
        .sType = VK_STRUCTURE_TYPE_SUBMIT_INFO,
        .commandBufferCount = 1, .pCommandBuffers = &command,
    };

    struct calibration before = {0}, after = {0}, later = {0};
    CHECK(calibrate(device, get_timestamps, &before));
    CHECK(vkQueueSubmit(queue, 1, &submit, fence));
    CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, UINT64_C(5000000000)));
    uint64_t query[2] = {0, 0};
    CHECK(vkGetQueryPoolResults(device, query_pool, 0, 1, sizeof(query), query,
                               sizeof(query), VK_QUERY_RESULT_64_BIT |
                               VK_QUERY_RESULT_WITH_AVAILABILITY_BIT));
    REQUIRE(query[1] != 0, "Completed submission did not make the GPU query available");
    CHECK(calibrate(device, get_timestamps, &after));
    const uint64_t span = ticks_between(before.gpu, after.gpu, mask);
    const uint64_t query_offset = ticks_between(before.gpu, query[0], mask);
    REQUIRE(span > 0 && span <= mask / 2 && query_offset <= span,
            "GPU query is not contained between DEVICE calibrations");
    printf("query: before=%" PRIu64 " gpuQuery=%" PRIu64 " after=%" PRIu64
           " availability=%" PRIu64 "\n",
           before.gpu, query[0], after.gpu, query[1]);

    /* A 100 ms idle sample distinguishes persistent hardware ticks from a
     * submission sequence number. Actual RAW elapsed time is measured below;
     * the requested sleep duration is never substituted for a measurement. */
    struct timespec remaining = {.tv_sec = 0, .tv_nsec = 100000000};
    while (nanosleep(&remaining, &remaining) < 0)
        REQUIRE(errno == EINTR, "Cannot wait for the persistent-counter sample");
    CHECK(calibrate(device, get_timestamps, &later));
    REQUIRE(later.cpu > after.cpu, "CLOCK_MONOTONIC_RAW did not advance");
    const uint64_t gpu_ticks = ticks_between(after.gpu, later.gpu, mask);
    REQUIRE(gpu_ticks > 0 && gpu_ticks <= mask / 2,
            "GPU persistent counter did not advance unambiguously while idle");
    const uint64_t cpu_ns = later.cpu - after.cpu;
    const long double gpu_ns = (long double)gpu_ticks * period;
    /* maxDeviation bounds each calibration's clock correlation. Include the
     * period's float representation error and one tick of quantization. */
    const long double uncertainty = (long double)after.deviation +
        (long double)later.deviation + period + gpu_ns * FLT_EPSILON;
    const long double error = fabsl(gpu_ns - (long double)cpu_ns);
    printf("frequency: gpuTicks=%" PRIu64 " rawElapsed=%" PRIu64
           " ns measured=%.6Lf MHz error=%.3Lf ns bound=%.3Lf ns"
           " deviations=%" PRIu64 "/%" PRIu64 " ns\n",
           gpu_ticks, cpu_ns, (long double)gpu_ticks * 1000.0L / cpu_ns,
           error, uncertainty, after.deviation, later.deviation);
    REQUIRE(uncertainty < (long double)cpu_ns,
            "Calibration uncertainty is too large to establish counter progress");
    REQUIRE(error <= uncertainty,
            "19.2 MHz GPU ticks disagree with RAW elapsed time beyond calibration uncertainty");

    vkDestroyFence(device, fence, NULL);
    vkDestroyCommandPool(device, command_pool, NULL);
    vkDestroyQueryPool(device, query_pool, NULL);
    vkDestroyDevice(device, NULL);
    vkDestroyInstance(instance, NULL);
    puts("PASS: submitted Adreno GPU timestamp lies between calibrations; persistent 19.2 MHz ticks agree with CLOCK_MONOTONIC_RAW within reported uncertainty");
    return 0;
}
