import XCTest
import UIKit
@testable import OrchMobile

final class PairingTests: XCTestCase {
    func testParsesContractLink() throws {
        let l = try PairingLink("orch://pair?relay=https%3A%2F%2Frelay.severin.io&code=pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V")
        XCTAssertEqual(l.relay.absoluteString, "https://relay.severin.io"); XCTAssertEqual(l.code, "pc_Tg5Yh7Uj9Ik2Ol4Pz6Xc8V"); XCTAssertEqual(l.host, "relay.severin.io")
    }
    func testRoundTripSample() throws { XCTAssertEqual(try PairingLink(PairingLink.sample.link), PairingLink.sample) }
    func testRejectsBadLinks() {
        for bad in ["", "https://relay.severin.io", "orch://pair?code=pc_x12345678", "orch://pair?relay=https%3A%2F%2Fa.io",
                    "orch://other?relay=https%3A%2F%2Fa.io&code=pc_abcdefgh", "orch://pair?relay=ftp%3A%2F%2Fa.io&code=pc_abcdefgh",
                    "orch://pair?relay=https%3A%2F%2Fa.io&code=xx_abcdefgh"] {
            XCTAssertThrowsError(try PairingLink(bad), bad)
        }
    }
    func testRelayMustBeHttpsOrThisDevice() throws {
        for bad in ["http%3A%2F%2Frelay.severin.io", "http%3A%2F%2F192.168.1.20%3A8080", "http%3A%2F%2Fmac.local"] {
            XCTAssertThrowsError(try PairingLink("orch://pair?relay=\(bad)&code=pc_abcdefgh"), bad)
        }
        XCTAssertNoThrow(try PairingLink("orch://pair?relay=http%3A%2F%2F127.0.0.1%3A8080&code=pc_abcdefgh"))
        XCTAssertNoThrow(try PairingLink("orch://pair?relay=HTTPS%3A%2F%2Frelay.severin.io&code=pc_abcdefgh"))
    }

    @MainActor func testPastedInvitationLeavesTheClipboard() {
        let board = UIPasteboard.withUniqueName()
        defer { UIPasteboard.remove(withName: board.name) }
        board.string = "not an invitation"
        XCTAssertNil(InvitePaste.take(from: board))
        XCTAssertEqual(board.string, "not an invitation", "other clipboard text is left alone")
        board.string = PairingLink.sample.link
        XCTAssertEqual(InvitePaste.take(from: board), PairingLink.sample.link)
        XCTAssertNil(board.string, "the one-time code does not stay on the clipboard")
    }

    func testDecodesContractExampleLink() throws {
        let ex = try Example.find("POST", "/admin/api/phones")
        let link = (try JSONSerialization.jsonObject(with: ex.responseData) as! [String: Any])["link"] as! String
        XCTAssertNoThrow(try PairingLink(link))
    }
}
