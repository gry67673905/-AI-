package com.example.aicompanion.portal.business;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import com.example.aicompanion.portal.model.PortalContract.Role;
import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import org.junit.Test;

public class PortalBusinessPoliciesTest {
    @Test
    public void dynamicFormValidatorChecksRequiredTypeAndLength() {
        JsonObject schema = JsonParser.parseString("{\"required\":[\"name\",\"age\"],\"properties\":{\"name\":{\"type\":\"string\",\"maxLength\":4},\"age\":{\"type\":\"integer\"}}}").getAsJsonObject();
        JsonObject invalid = JsonParser.parseString("{\"name\":\"超过四个字符\",\"age\":1.5}").getAsJsonObject();
        DynamicFormValidator.ValidationResult result = new DynamicFormValidator().validate(schema, invalid);

        assertFalse(result.isValid());
        assertEquals(2, result.getErrors().size());

        JsonObject valid = JsonParser.parseString("{\"name\":\"张三\",\"age\":18}").getAsJsonObject();
        assertTrue(new DynamicFormValidator().validate(schema, valid).isValid());
    }

    @Test
    public void materialPolicyExplainsConditionalMissingMaterial() {
        JsonArray requirements = JsonParser.parseString("[{\"id\":\"id-card\",\"name\":\"身份证\",\"kind\":\"REQUIRED\"},{\"id\":\"proof\",\"name\":\"企业证明\",\"kind\":\"CONDITIONAL\",\"condition\":{\"field\":\"type\",\"eq\":\"ENTERPRISE\"},\"trigger_reason\":\"企业申请触发\"}]").getAsJsonArray();
        JsonArray uploaded = JsonParser.parseString("[{\"requirement_id\":\"id-card\"}]").getAsJsonArray();
        JsonObject form = JsonParser.parseString("{\"type\":\"ENTERPRISE\"}").getAsJsonObject();

        MaterialCompletionPolicy.Result result = new MaterialCompletionPolicy().evaluate(requirements, uploaded, form);

        assertFalse(result.isComplete());
        assertEquals("proof", result.getMissing().get(0).getRequirementId());
        assertEquals("企业申请触发", result.getMissing().get(0).getReason());
    }

    @Test
    public void roleNavigationDoesNotExposeAdminSectionsToCitizen() {
        RoleNavigationPolicy policy = new RoleNavigationPolicy();
        assertTrue(policy.canNavigate(Role.CITIZEN, "applications"));
        assertFalse(policy.canNavigate(Role.CITIZEN, "admin_people"));
        assertTrue(policy.canNavigate(Role.ADMIN, "admin_audit"));
    }

    @Test
    public void displayPolicyDropsTokensAndMasksIdentifiers() {
        JsonElement input = JsonParser.parseString("{\"access_token\":\"secret\",\"nested\":{\"password\":\"hidden\"},\"text\":\"电话13812345678，身份证110101199001011234，Authorization: Bearer web-secret\"}");
        JsonObject safe = new SensitiveDisplayPolicy().sanitize(input).getAsJsonObject();

        assertFalse(safe.has("access_token"));
        assertFalse(safe.getAsJsonObject("nested").has("password"));
        assertFalse(safe.get("text").getAsString().contains("13812345678"));
        assertFalse(safe.get("text").getAsString().contains("110101199001011234"));
        assertFalse(safe.get("text").getAsString().contains("web-secret"));
    }
}
