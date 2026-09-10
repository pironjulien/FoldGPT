package app.foldgpt;

import org.json.JSONObject;
import org.junit.Test;
import static org.junit.Assert.*;

public class FoldSmsRequestTest {
    @Test public void bindsSearchTextAsLiteralAndUsesStablePagination() throws Exception {
        JSONObject input = new JSONObject().put("text", "100%_\\' OR 1=1")
                .put("dateAfter", 123L).put("dateBefore", 456L).put("beforeId", 88).put("limit", 10);
        FoldSmsRequest request = FoldSmsRequest.search(input, false);
        assertEquals("body LIKE ? ESCAPE '\\' AND date >= ? AND date < ? AND _id < ?", request.selection);
        assertArrayEquals(new String[]{"%100\\%\\_\\\\' OR 1=1%", "123", "456", "88"}, request.selectionArgs);
        assertEquals(10, request.limit);
        assertFalse(request.selection.contains("100"));
    }

    @Test public void rejectsUnfilteredDumpAndBadBoundsWithoutEchoingPrivateInput() throws Exception {
        for (JSONObject value : new JSONObject[]{new JSONObject(), new JSONObject().put("limit", 10),
                new JSONObject().put("beforeId", 500), new JSONObject().put("text", " "),
                new JSONObject().put("text", "private-sms").put("limit", 0),
                new JSONObject().put("text", "private-sms").put("limit", 51),
                new JSONObject().put("threadId", 1.5), new JSONObject().put("threadId", "2"),
                new JSONObject().put("threadId", 0), new JSONObject().put("dateAfter", 30).put("dateBefore", 30),
                new JSONObject().put("text", "private-sms").put("selection", "1=1"),
                new JSONObject().put("text", "private-sms").put("archived", true)}) {
            try { FoldSmsRequest.search(value, false); fail("Invalid search accepted"); }
            catch (IllegalArgumentException expected) { assertEquals("invalid_sms_arguments", expected.getMessage()); }
        }
    }

    @Test public void threadReadRequiresExactThreadAndAllowsBoundedPagination() throws Exception {
        FoldSmsRequest query = FoldSmsRequest.search(new JSONObject().put("threadId", 123)
                .put("beforeId", 99).put("limit", 50), true);
        assertEquals("thread_id = ? AND _id < ?", query.selection);
        assertArrayEquals(new String[]{"123", "99"}, query.selectionArgs);
        try { FoldSmsRequest.search(new JSONObject().put("text", "private-sms"), true); fail(); }
        catch (IllegalArgumentException expected) { }
    }

    @Test public void recipientRequiresOneUnambiguousNumericDestination() throws Exception {
        assertEquals("+33612345678", FoldSmsRequest.recipient(new JSONObject().put("recipient", "+33 (6)12-34.56 78")));
        assertEquals("12345", FoldSmsRequest.recipient(new JSONObject().put("recipient", "12345")));
        for (String value : new String[]{"Alice", "tel:+33612345678", "123;456", "123,456", "*123#", "+12+34", "12", "１２３４"}) {
            try { FoldSmsRequest.recipient(new JSONObject().put("recipient", value)); fail(); }
            catch (IllegalArgumentException expected) { assertEquals("invalid_sms_arguments", expected.getMessage()); }
        }
    }

    @Test public void preservesReviewBodyExactlyButRejectsNullAndBrokenUnicode() throws Exception {
        String text = " Une réponse\navec emoji 📱 ";
        assertEquals(text, FoldSmsRequest.body(new JSONObject().put("body", text)));
        for (String invalid : new String[]{"", "\n ", "private\u0000sms", "\ud800", "\udc00", "x".repeat(4097)}) {
            try { FoldSmsRequest.body(new JSONObject().put("body", invalid)); fail(); }
            catch (IllegalArgumentException expected) { }
        }
    }
}
