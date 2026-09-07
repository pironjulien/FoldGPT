/* SPDX-License-Identifier: MIT
 * Isolated Mesa 26.2.2 diagnostic. Metadata only: no clear colors, pixels,
 * image bytes, buffer contents, descriptor contents or shader contents.
 * Included once from tu_cmd_buffer.cc by mesa-gmem-metadata.patch.
 */
#include <algorithm>
#include <cerrno>
#include <cinttypes>
#include <cstdio>
#include <fcntl.h>
#include <initializer_list>
#include <mutex>
#include <unistd.h>

namespace {
constexpr unsigned fg_trace_capacity = 8192; /* power-of-two bounded ring */
constexpr unsigned fg_trace_words = 32;
struct fg_trace_entry {
   uint64_t sequence;
   unsigned kind, count;
   int64_t words[fg_trace_words];
};
struct fg_trace_ring {
   std::mutex mutex;
   std::atomic<uint64_t> dropped{0};
   uint64_t next = 0;
   fg_trace_entry entries[fg_trace_capacity] = {};
};
fg_trace_ring fg_trace;

/* Called only while holding the ring mutex. No allocations or I/O. */
void fg_trace_add(unsigned kind, std::initializer_list<int64_t> data)
{
   assert(data.size() <= fg_trace_words);
   uint64_t seq = fg_trace.next++;
   auto &entry = fg_trace.entries[seq & (fg_trace_capacity - 1)];
   entry.sequence = seq;
   entry.kind = kind;
   entry.count = data.size();
   std::copy(data.begin(), data.end(), entry.words);
}

/* IDs are process-local object addresses, never GPU IOVAs or memory contents. */
int64_t fg_id(const void *p) { return static_cast<int64_t>(reinterpret_cast<uintptr_t>(p)); }

void fg_trace_render_pass(struct tu_cmd_buffer *cmd, bool sysmem, bool binning)
{
   uint64_t flags = tu_env.debug.load(std::memory_order_relaxed);
   if (!(flags & TU_DEBUG_FOLDGPT_GMEM_TRACE))
      return;
   std::unique_lock<std::mutex> lock(fg_trace.mutex, std::try_to_lock);
   if (!lock.owns_lock()) {
      fg_trace.dropped.fetch_add(1, std::memory_order_relaxed);
      return;
   }
   flags = tu_env.debug.load(std::memory_order_acquire);
   if (!(flags & TU_DEBUG_FOLDGPT_GMEM_TRACE))
      return;
   const auto *pass = cmd->state.pass;
   const auto *tiling = cmd->state.tiling;
   const auto *fb = cmd->state.framebuffer;
   if (!pass || !tiling || !fb) {
      fg_trace_add(0, {fg_id(cmd), 1});
      return;
   }
   const uint64_t pass_id = fg_trace.next;
   const unsigned areas = cmd->state.per_layer_render_area ? pass->num_views : 1;
   fg_trace_add(1, {fg_id(cmd), static_cast<int64_t>(flags), sysmem, binning,
      cmd->state.renderpass_cb_disabled, cmd->state.rp.drawcall_count,
      pass->attachment_count, pass->user_attachment_count, pass->subpass_count,
      cmd->state.gmem_layout, cmd->state.gmem_layout_divisor,
      fb->width, fb->height, fb->layers, tiling->tile0.width, tiling->tile0.height,
      tiling->vsc.tile_count.width, tiling->vsc.tile_count.height,
      pass->has_msrtss, pass->has_fdm, pass->allow_ib2_skipping,
      pass->has_cond_load_store, areas, pass->gmem_pixels[0], pass->gmem_pixels[1],
      cmd->state.fdm_enabled, cmd->state.fdm_subsampled,
      static_cast<uint32_t>(cmd->state.renderpass_cache.flush_bits),
      static_cast<uint32_t>(cmd->state.renderpass_cache.pending_flush_bits)});
   for (unsigned i = 0; i < MIN2(areas, 32u); ++i) {
      const auto &r = cmd->state.render_areas[i];
      fg_trace_add(2, {static_cast<int64_t>(pass_id), i, r.offset.x, r.offset.y,
         r.extent.width, r.extent.height});
   }
   /* Every actual attachment is recorded; the global ring remains bounded. */
   for (unsigned i = 0; i < pass->attachment_count; ++i) {
      const auto &a = pass->attachments[i];
      const auto *v = cmd->state.attachments ? cmd->state.attachments[i] : nullptr;
      fg_trace_add(3, {static_cast<int64_t>(pass_id), i, a.format, a.samples, a.cpp,
         a.clear_mask, a.load, a.store, a.load_stencil, a.store_stencil,
         a.gmem, a.gmem_offset[0], a.gmem_offset[1],
         a.gmem_offset_stencil[0], a.gmem_offset_stencil[1],
         a.will_be_resolved, a.first_subpass_idx, a.last_subpass_idx,
         a.cond_load_allowed, a.cond_store_allowed, a.user_att, a.remapped_clear_att,
         fg_id(v), v ? fg_id(v->image) : 0,
         v ? v->vk.extent.width : 0, v ? v->vk.extent.height : 0,
         v ? v->vk.extent.depth : 0, v ? v->view.ubwc_enabled : 0,
         v ? v->view.is_mutable : 0, a.used_views, a.resolve_views});
   }
   for (unsigned i = 0; i < pass->subpass_count; ++i) {
      const auto &s = pass->subpasses[i];
      fg_trace_add(4, {static_cast<int64_t>(pass_id), i, s.samples, s.color_count,
         s.input_count, s.resolve_count, s.unresolve_count,
         s.depth_stencil_attachment.attachment, s.depth_used, s.stencil_used,
         s.multiview_mask, s.feedback_loop_color, s.feedback_loop_ds,
         s.raster_order_attachment_access, s.custom_resolve});
   }
}
} /* namespace */

/* Called from the existing TU_DEBUG_FILE watcher after recording is disabled.
 * No output operation happens in the rendering path. One dump per unique path.
 */
void tu_foldgpt_dump_gmem_trace(void)
{
   if (TU_DEBUG(FOLDGPT_GMEM_TRACE)) {
      mesa_loge("FoldGPT GMEM diagnostic: remove gmemtrace before gmemdump");
      return;
   }
   const char *path = os_get_option("FOLDGPT_GMEM_TRACE_PATH");
   if (!path || path[0] != '/') {
      mesa_loge("FoldGPT GMEM diagnostic: absolute FOLDGPT_GMEM_TRACE_PATH required");
      return;
   }
   int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
   if (fd < 0) {
      mesa_loge("FoldGPT GMEM diagnostic: cannot create new metadata file (%d)", errno);
      return;
   }
   FILE *out = fdopen(fd, "w");
   if (!out) {
      close(fd);
      mesa_loge("FoldGPT GMEM diagnostic: fdopen failed (%d)", errno);
      return;
   }
   std::lock_guard<std::mutex> lock(fg_trace.mutex);
   uint64_t start = fg_trace.next > fg_trace_capacity ? fg_trace.next - fg_trace_capacity : 0;
   fprintf(out, "{\"schema\":\"foldgpt-gmem-metadata-v1\",\"capacity\":%u,\"total\":%" PRIu64
      ",\"overwritten\":%" PRIu64 ",\"dropped_lock_groups\":%" PRIu64 "}\n",
      fg_trace_capacity, fg_trace.next, start, fg_trace.dropped.load());
   for (uint64_t seq = start; seq < fg_trace.next; ++seq) {
      const auto &e = fg_trace.entries[seq & (fg_trace_capacity - 1)];
      fprintf(out, "{\"seq\":%" PRIu64 ",\"kind\":%u,\"v\":[", e.sequence, e.kind);
      for (unsigned i = 0; i < e.count; ++i)
         fprintf(out, "%s%" PRId64, i ? "," : "", e.words[i]);
      fputs("]}\n", out);
   }
   int failed = fflush(out);
   if (!failed)
      failed = fsync(fd);
   if (fclose(out))
      failed = -1;
   if (failed)
      mesa_loge("FoldGPT GMEM diagnostic: metadata dump incomplete");
   else
      mesa_loge("FoldGPT GMEM diagnostic: metadata dump complete (%" PRIu64 " events)", fg_trace.next - start);
}

void tu_foldgpt_trace_clear(struct tu_cmd_buffer *cmd, uint32_t attachment_count,
                          const VkClearAttachment *attachments,
                          uint32_t rect_count, const VkClearRect *rects)
{
   uint64_t flags = tu_env.debug.load(std::memory_order_relaxed);
   if (!(flags & TU_DEBUG_FOLDGPT_GMEM_TRACE))
      return;
   std::unique_lock<std::mutex> lock(fg_trace.mutex, std::try_to_lock);
   if (!lock.owns_lock()) {
      fg_trace.dropped.fetch_add(1, std::memory_order_relaxed);
      return;
   }
   flags = tu_env.debug.load(std::memory_order_acquire);
   if (!(flags & TU_DEBUG_FOLDGPT_GMEM_TRACE))
      return;
   const uint64_t clear_id = fg_trace.next;
   fg_trace_add(5, {fg_id(cmd), static_cast<int64_t>(flags), attachment_count,
      rect_count, cmd->state.pass && cmd->state.subpass ?
         cmd->state.subpass - cmd->state.pass->subpasses : -1});
   for (uint32_t i = 0; i < attachment_count; ++i)
      fg_trace_add(6, {static_cast<int64_t>(clear_id), i,
         attachments[i].aspectMask, attachments[i].colorAttachment});
   for (uint32_t i = 0; i < rect_count; ++i) {
      const auto &r = rects[i];
      fg_trace_add(7, {static_cast<int64_t>(clear_id), i, r.rect.offset.x,
         r.rect.offset.y, r.rect.extent.width, r.rect.extent.height,
         r.baseArrayLayer, r.layerCount});
   }
}
