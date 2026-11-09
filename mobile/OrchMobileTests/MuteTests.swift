import XCTest
@testable import OrchMobile

final class MuteTests: XCTestCase {
    private func date(_ value: String) -> Date { MuteRules.date(value)! }

    func testSettingsCompatibility() throws {
        let old = Data(#"{"speak":"auto","swiss_german":false,"tts_cap_usd":10,"tts_used_usd_month":0}"#.utf8)
        let settings = try JSONCoding.decoder.decode(PhoneSettings.self, from: old)
        XCTAssertNil(settings.muteAllUntil)
        XCTAssertNil(settings.groupMutes)
        let new = Data(#"{"speak":"always","swiss_german":true,"tts_cap_usd":20,"tts_used_usd_month":1,"mute_all_until":"forever","group_mutes":[{"host":"ws_pilatus001","id":"grp_t_7k3f9q","muted_until":"forever"}]}"#.utf8)
        let muted = try JSONCoding.decoder.decode(PhoneSettings.self, from: new)
        XCTAssertEqual(muted.muteAllUntil, "forever")
        XCTAssertEqual(muted.groupMutes?.first?.key, GroupKey(host: "ws_pilatus001", id: "grp_t_7k3f9q"))
        XCTAssertEqual(muted.groupMutes?.first?.mutedUntil, "forever")
    }

    func testGroupResponseAndExplicitNullPatches() throws {
        let data = Data(#"{"host":"ws_pilatus001","id":"grp_t_7k3f9q","muted_until":null}"#.utf8)
        let group = try JSONCoding.decoder.decode(GroupMute.self, from: data)
        XCTAssertEqual(group.host, "ws_pilatus001")
        XCTAssertEqual(group.id, "grp_t_7k3f9q")
        XCTAssertNil(group.mutedUntil)
        let all = try JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(MuteAllPatch(mute: .off))) as? [String: Any]
        XCTAssertTrue(all?["mute_all_until"] is NSNull)
        let patch = try JSONSerialization.jsonObject(with: JSONCoding.encoder.encode(GroupMutePatch(mute: .off))) as? [String: Any]
        XCTAssertTrue(patch?["muted_until"] is NSNull)
    }

    func testActiveMute() {
        let now = date("2026-11-09T10:00:00Z")
        XCTAssertTrue(MuteRules.isMuted("forever", now: now))
        XCTAssertTrue(MuteRules.isMuted("2026-11-09T11:00:00Z", now: now))
        XCTAssertTrue(MuteRules.isMuted("2026-11-09T10:00:00.500Z", now: now))
        XCTAssertFalse(MuteRules.isMuted("2026-11-09T09:00:00Z", now: now))
        XCTAssertFalse(MuteRules.isMuted("2026-11-09T10:00:00Z", now: now))
        XCTAssertFalse(MuteRules.isMuted(nil, now: now))
    }

    func testNextLocalEight() {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Europe/Zurich")!
        let cases = [
            ("2026-11-09T06:59:00Z", "2026-11-09T07:00:00Z"),
            ("2026-11-09T07:00:00Z", "2026-11-10T07:00:00Z"),
            ("2026-11-09T10:00:00Z", "2026-11-10T07:00:00Z"),
            ("2026-03-28T10:00:00Z", "2026-03-29T06:00:00Z"),
            ("2026-10-24T10:00:00Z", "2026-10-25T07:00:00Z")
        ]
        for (now, expected) in cases {
            XCTAssertEqual(MuteChoice.morning.mute(now: date(now), calendar: calendar), .until(date(expected)))
        }
        let now = date("2026-11-09T10:00:00Z")
        XCTAssertEqual(MuteChoice.hour.mute(now: now), .until(now.addingTimeInterval(3600)))
        XCTAssertEqual(MuteChoice.forever.mute(now: now), .forever)
    }

    func testContractVectors() throws {
        struct Vectors: Decodable { let cases: [Case] }
        struct Case: Decodable {
            let name: String
            let now: String
            let message: Message
            let phone: Phone
            let push: Bool
        }
        struct Message: Decodable { let from: String; let body: Body }
        struct Body: Decodable { let group: Ref?; let groupRef: Ref? }
        struct Ref: Decodable { let host: String; let id: String }
        struct Phone: Decodable {
            let muteAllUntil: String?
            let workspaceMutes: [String: String]?
            let groupMutes: [GroupMute]?
        }
        let root = URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent()
        let data = try Data(contentsOf: root.appendingPathComponent("contracts/vectors/mute-v1.json"))
        let vectors = try JSONCoding.decoder.decode(Vectors.self, from: data)
        XCTAssertFalse(vectors.cases.isEmpty)
        for item in vectors.cases {
            let ref = item.message.body.group ?? item.message.body.groupRef
            let muted = MuteRules.isMuted(all: item.phone.muteAllUntil,
                                          workspace: item.phone.workspaceMutes?[item.message.from],
                                          group: ref.map { GroupKey(host: $0.host, id: $0.id) },
                                          groups: item.phone.groupMutes ?? [], now: date(item.now))
            XCTAssertEqual(item.push, !muted, item.name)
        }
    }

    func testMockMuteState() async throws {
        let relay = MockRelay()
        let all = try await relay.muteAll(.forever)
        XCTAssertEqual(all.muteAllUntil, "forever")
        let key = GroupKey(host: "ws_pilatus001", id: "grp_t_7k3f9q")
        _ = try await relay.setGroupMute(key, mute: .forever)
        let settings = try await relay.settings()
        XCTAssertEqual(settings.groupMutes?.first?.key, key)
        _ = try await relay.setGroupMute(key, mute: .off)
        let cleared = try await relay.muteAll(.off)
        XCTAssertNil(cleared.muteAllUntil)
        XCTAssertEqual(cleared.groupMutes, [])
    }
}
