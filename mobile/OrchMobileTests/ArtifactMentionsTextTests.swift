import XCTest
import SwiftUI
@testable import OrchMobile

final class ArtifactMentionsTextTests: XCTestCase {
    func testOnlyAttachedMentionHasLink() {
        let attachment = TicketSnapshot.Attachment(kind: "file", name: "x.md", artifactId: "draft id/1")
        let text = "Read artifacts/x.md, then notes/old-plan.md and https://example.com/x.md or plain words."
        let attributed = ArtifactMentions.attributed(text, attachments: [attachment])
        XCTAssertEqual(String(attributed.characters), text)
        var linkedRuns = 0
        for run in attributed.runs {
            let content = String(attributed[run.range].characters)
            if content == "artifacts/x.md" {
                linkedRuns += 1
                XCTAssertEqual(run.link?.absoluteString, "orch-artifact://draft%20id%2F1")
            } else {
                XCTAssertNil(run.link, content)
            }
        }
        XCTAssertEqual(linkedRuns, 1)
    }

    func testAttachmentIdRoundTripsAndRejectsOtherSchemes() throws {
        let attachment = TicketSnapshot.Attachment(kind: "file", name: "x.md", artifactId: "draft id/1")
        let attributed = ArtifactMentions.attributed("artifacts/x.md", attachments: [attachment])
        let url = try XCTUnwrap(attributed.runs.first?.link)
        XCTAssertEqual(ArtifactMentions.attachmentId(from: url), attachment.id)
        XCTAssertNil(ArtifactMentions.attachmentId(from: try XCTUnwrap(URL(string: "https://example.com/x.md"))))
    }

    func testLinkAttachmentNeverMatches() {
        let attachment = TicketSnapshot.Attachment(kind: "link", title: "x.md", url: "https://example.com/x.md", name: "x.md")
        let text = "x.md artifacts/x.md https://example.com/x.md"
        XCTAssertTrue(ArtifactMentions.mentions(in: text, attachments: [attachment]).isEmpty)
        for run in ArtifactMentions.attributed(text, attachments: [attachment]).runs {
            XCTAssertNil(run.link)
        }
    }
}
