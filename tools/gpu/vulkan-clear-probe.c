/* A real, bounded GPU queue test: optimal image clear, readback and verification.
 * No window, files, network or changes to another process. Select the isolated
 * Vulkan ICD with VK_DRIVER_FILES before launching this executable. */
#include <vulkan/vulkan.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define CHECK(call) do { VkResult r = (call); if (r != VK_SUCCESS) { fprintf(stderr, "%s failed: VkResult=%d\n", #call, r); return 1; } } while (0)

static VKAPI_ATTR VkBool32 VKAPI_CALL debug_message(VkDebugUtilsMessageSeverityFlagBitsEXT severity,
        VkDebugUtilsMessageTypeFlagsEXT type, const VkDebugUtilsMessengerCallbackDataEXT *data, void *user) {
    (void)severity; (void)type; (void)user;
    fprintf(stderr, "Vulkan diagnostic: %s\n", data->pMessage);
    return VK_FALSE;
}

static uint32_t memory_type(VkPhysicalDevice gpu, uint32_t allowed, VkMemoryPropertyFlags flags) {
    VkPhysicalDeviceMemoryProperties memory;
    vkGetPhysicalDeviceMemoryProperties(gpu, &memory);
    for (uint32_t i = 0; i < memory.memoryTypeCount; i++)
        if ((allowed & (1u << i)) && (memory.memoryTypes[i].propertyFlags & flags) == flags) return i;
    fprintf(stderr, "Required GPU memory type unavailable\n");
    exit(1);
}

int main(void) {
    const uint32_t width = 64, height = 64;
    const VkDeviceSize bytes = width * height * 4;
    VkApplicationInfo app = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "FoldGPT isolated GPU probe", .apiVersion = VK_API_VERSION_1_1};
    const char *debug_extension = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
    VkDebugUtilsMessengerCreateInfoEXT debug = {.sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT,
        .messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT,
        .messageType = VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT,
        .pfnUserCallback = debug_message};
    VkInstanceCreateInfo instance_info = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pNext = &debug,
        .pApplicationInfo = &app, .enabledExtensionCount = 1, .ppEnabledExtensionNames = &debug_extension};
    VkInstance instance;
    CHECK(vkCreateInstance(&instance_info, NULL, &instance));
    PFN_vkCreateDebugUtilsMessengerEXT create_debug = (PFN_vkCreateDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance, "vkCreateDebugUtilsMessengerEXT");
    PFN_vkDestroyDebugUtilsMessengerEXT destroy_debug = (PFN_vkDestroyDebugUtilsMessengerEXT)vkGetInstanceProcAddr(instance, "vkDestroyDebugUtilsMessengerEXT");
    if (!create_debug || !destroy_debug) { fprintf(stderr, "Debug-utils entry points unavailable\n"); return 1; }
    VkDebugUtilsMessengerEXT messenger;
    CHECK(create_debug(instance, &debug, NULL, &messenger));
    uint32_t count = 0;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, NULL));
    if (count != 1) { fprintf(stderr, "Expected exactly one isolated GPU; found %u\n", count); return 1; }
    VkPhysicalDevice gpu;
    CHECK(vkEnumeratePhysicalDevices(instance, &count, &gpu));
    VkPhysicalDeviceProperties properties;
    vkGetPhysicalDeviceProperties(gpu, &properties);
    printf("GPU=%s type=%u vendor=0x%x device=0x%x api=%u.%u.%u\n", properties.deviceName,
           properties.deviceType, properties.vendorID, properties.deviceID,
           VK_API_VERSION_MAJOR(properties.apiVersion), VK_API_VERSION_MINOR(properties.apiVersion), VK_API_VERSION_PATCH(properties.apiVersion));
    if (properties.deviceType != VK_PHYSICAL_DEVICE_TYPE_INTEGRATED_GPU ||
            (!strstr(properties.deviceName, "Adreno") && !strstr(properties.deviceName, "Turnip"))) {
        fprintf(stderr, "Refusing to report software or unrelated GPU as Adreno proof\n"); return 1;
    }
    uint32_t family_count = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, NULL);
    VkQueueFamilyProperties *families = calloc(family_count, sizeof(*families));
    if (!families) return 1;
    vkGetPhysicalDeviceQueueFamilyProperties(gpu, &family_count, families);
    uint32_t family = UINT32_MAX;
    for (uint32_t i = 0; i < family_count; i++) if (families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) { family = i; break; }
    free(families);
    if (family == UINT32_MAX) { fprintf(stderr, "No graphics queue\n"); return 1; }
    float priority = 1.0f;
    VkDeviceQueueCreateInfo queue_info = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = family, .queueCount = 1, .pQueuePriorities = &priority};
    VkDeviceCreateInfo device_info = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &queue_info};
    VkDevice device;
    CHECK(vkCreateDevice(gpu, &device_info, NULL, &device));
    VkQueue queue;
    vkGetDeviceQueue(device, family, 0, &queue);
    VkImageCreateInfo image_info = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_R8G8B8A8_UNORM, .extent = {width, height, 1}, .mipLevels = 1, .arrayLayers = 1,
        .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VkImage image;
    CHECK(vkCreateImage(device, &image_info, NULL, &image));
    VkMemoryRequirements requirements;
    vkGetImageMemoryRequirements(device, image, &requirements);
    VkMemoryAllocateInfo allocation = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = requirements.size,
        .memoryTypeIndex = memory_type(gpu, requirements.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    VkDeviceMemory image_memory;
    CHECK(vkAllocateMemory(device, &allocation, NULL, &image_memory));
    CHECK(vkBindImageMemory(device, image, image_memory, 0));
    VkBufferCreateInfo buffer_info = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bytes,
        .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT, .sharingMode = VK_SHARING_MODE_EXCLUSIVE};
    VkBuffer buffer;
    CHECK(vkCreateBuffer(device, &buffer_info, NULL, &buffer));
    vkGetBufferMemoryRequirements(device, buffer, &requirements);
    allocation.allocationSize = requirements.size;
    allocation.memoryTypeIndex = memory_type(gpu, requirements.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory buffer_memory;
    CHECK(vkAllocateMemory(device, &allocation, NULL, &buffer_memory));
    CHECK(vkBindBufferMemory(device, buffer, buffer_memory, 0));
    VkCommandPoolCreateInfo pool_info = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = family};
    VkCommandPool pool;
    CHECK(vkCreateCommandPool(device, &pool_info, NULL, &pool));
    VkCommandBufferAllocateInfo command_info = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
        .commandPool = pool, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkCommandBuffer command;
    CHECK(vkAllocateCommandBuffers(device, &command_info, &command));
    VkCommandBufferBeginInfo begin = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
    CHECK(vkBeginCommandBuffer(command, &begin));
    VkImageSubresourceRange range = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .levelCount = 1, .layerCount = 1};
    VkImageMemoryBarrier barrier = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER,
        .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED,
        .newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
        .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = image, .subresourceRange = range};
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &barrier);
    VkClearColorValue color = {.float32 = {1, 0, 1, 1}};
    vkCmdClearColorImage(command, image, VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &color, 1, &range);
    barrier.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
    barrier.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
    barrier.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
    barrier.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &barrier);
    VkBufferImageCopy copy = {.imageSubresource = {.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT, .layerCount = 1}, .imageExtent = {width, height, 1}};
    vkCmdCopyImageToBuffer(command, image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buffer, 1, &copy);
    VkMemoryBarrier host_barrier = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &host_barrier, 0, NULL, 0, NULL);
    CHECK(vkEndCommandBuffer(command));
    VkFenceCreateInfo fence_info = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    VkFence fence;
    CHECK(vkCreateFence(device, &fence_info, NULL, &fence));
    VkSubmitInfo submit = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &command};
    CHECK(vkQueueSubmit(queue, 1, &submit, fence));
    CHECK(vkWaitForFences(device, 1, &fence, VK_TRUE, 5000000000ULL));
    uint8_t *pixels;
    CHECK(vkMapMemory(device, buffer_memory, 0, bytes, 0, (void **)&pixels));
    const uint8_t expected[4] = {255, 0, 255, 255};
    for (VkDeviceSize i = 0; i < bytes; i++) if (pixels[i] != expected[i % 4]) {
        fprintf(stderr, "GPU readback mismatch at byte %llu: expected %u actual %u\n", (unsigned long long)i, expected[i % 4], pixels[i]); return 1;
    }
    vkUnmapMemory(device, buffer_memory);
    printf("PASS: Adreno Vulkan queue submitted and completed; %ux%u offscreen pixels verified\n", width, height);
    vkDestroyFence(device, fence, NULL);
    vkDestroyCommandPool(device, pool, NULL);
    vkDestroyBuffer(device, buffer, NULL);
    vkFreeMemory(device, buffer_memory, NULL);
    vkDestroyImage(device, image, NULL);
    vkFreeMemory(device, image_memory, NULL);
    vkDestroyDevice(device, NULL);
    destroy_debug(instance, messenger, NULL);
    vkDestroyInstance(instance, NULL);
    return 0;
}
