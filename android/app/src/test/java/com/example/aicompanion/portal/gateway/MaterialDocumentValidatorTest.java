package com.example.aicompanion.portal.gateway;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertFalse;
import static org.junit.Assert.assertTrue;

import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;

import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.zip.ZipEntry;
import java.util.zip.ZipOutputStream;

public class MaterialDocumentValidatorTest {
    @Rule public final TemporaryFolder temporary = new TemporaryFolder();

    @Test public void acceptsMinimalMacroFreeDocxWithMatchingHash() throws Exception {
        File docx = docx(entries(
            "[Content_Types].xml", "<Types/>",
            "word/document.xml", "<w:document/>"
        ));
        String sha = MaterialDocumentValidator.sha256(docx);

        MaterialDocumentValidator.Result result = MaterialDocumentValidator.validate(docx, sha);

        assertTrue(result.isValid());
        assertEquals(sha, result.getSha256());
        assertEquals(docx.length(), result.getSize());
    }

    @Test public void rejectsHashMismatchMissingStructureAndExternalRelationship() throws Exception {
        File valid = docx(entries(
            "[Content_Types].xml", "<Types/>",
            "word/document.xml", "<w:document/>"
        ));
        assertEquals("document_hash_mismatch", MaterialDocumentValidator.validate(
            valid, "0000000000000000000000000000000000000000000000000000000000000000"
        ).getCode());

        File missing = docx(entries("[Content_Types].xml", "<Types/>"));
        MaterialDocumentValidator.Result missingResult = MaterialDocumentValidator.validate(
            missing, MaterialDocumentValidator.sha256(missing)
        );
        assertFalse(missingResult.isValid());
        assertEquals("invalid_docx_package", missingResult.getCode());

        File external = docx(entries(
            "[Content_Types].xml", "<Types/>",
            "word/document.xml", "<w:document/>",
            "word/_rels/document.xml.rels", "<Relationship TargetMode=\"External\" Target=\"https://example.invalid\"/>"
        ));
        MaterialDocumentValidator.Result externalResult = MaterialDocumentValidator.validate(
            external, MaterialDocumentValidator.sha256(external)
        );
        assertFalse(externalResult.isValid());
        assertEquals("unsafe_docx_content", externalResult.getCode());
    }

    @Test public void rejectsAltChunkAndGenericBinaryParts() throws Exception {
        File altChunk = docx(entries(
            "[Content_Types].xml", "<Types/>",
            "word/document.xml", "<w:document><w:body><w:altChunk r:id=\"external\"/></w:body></w:document>"
        ));
        assertEquals("unsafe_docx_content", MaterialDocumentValidator.validate(
            altChunk, MaterialDocumentValidator.sha256(altChunk)
        ).getCode());

        File binary = docx(entries(
            "[Content_Types].xml", "<Types/>",
            "word/document.xml", "<w:document/>",
            "customXml/payload.bin", "not allowed"
        ));
        assertEquals("unsafe_docx_content", MaterialDocumentValidator.validate(
            binary, MaterialDocumentValidator.sha256(binary)
        ).getCode());
    }

    private File docx(Map<String, String> entries) throws Exception {
        File file = temporary.newFile("document-" + System.nanoTime() + ".docx");
        try (ZipOutputStream output = new ZipOutputStream(new FileOutputStream(file))) {
            for (Map.Entry<String, String> item : entries.entrySet()) {
                output.putNextEntry(new ZipEntry(item.getKey()));
                output.write(item.getValue().getBytes(StandardCharsets.UTF_8));
                output.closeEntry();
            }
        }
        return file;
    }

    private static Map<String, String> entries(String... values) {
        Map<String, String> result = new LinkedHashMap<>();
        for (int index = 0; index < values.length; index += 2) result.put(values[index], values[index + 1]);
        return result;
    }
}
