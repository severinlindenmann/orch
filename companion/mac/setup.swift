// orch Companion, step 5 (ORCH-1195): explain the two Mac permissions before the Mac asks, start with the Mac, and
// update itself. Updates come only from a release signed by the same Apple team as the running app; an unsigned
// (ad-hoc) build never updates itself.

import AppKit
import AVFoundation
import CoreAudio
import Foundation
import Security
import ServiceManagement

let version = (Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String) ?? "0.0.0"
let releasesURL = URL(string: "https://api.github.com/repos/severinlindenmann/orch/releases?per_page=30")!
let releaseTag = "companion-v"
let updateEvery = 6.0 * 3600

// MARK: - permissions

enum Permission { case microphone, callSound }

func microphoneAllowed() -> Bool { AVCaptureDevice.authorizationStatus(for: .audio) == .authorized }

func askMicrophone(_ done: @escaping (Bool) -> Void) {
    AVCaptureDevice.requestAccess(for: .audio) { ok in DispatchQueue.main.async { done(ok) } }
}

/// macOS has no public way to read the "Screen & System Audio Recording" answer; making a tap of our own sound
/// once makes the Mac ask. We remember that we asked.
func askCallSound() {
    let mine = audioProcesses().filter { $0.pid == getpid() }.map { $0.object }
    let desc = CATapDescription(stereoMixdownOfProcesses: mine)
    desc.isPrivate = true
    var tap = AudioObjectID(kAudioObjectUnknown)
    if AudioHardwareCreateProcessTap(desc, &tap) == noErr { AudioHardwareDestroyProcessTap(tap) }
    UserDefaults.standard.set(true, forKey: "askedCallSound")
}

let setupTitle = "orch Companion records your calls for Meetings"
let setupIntro = "It records only after you said that everyone on the call agreed. Your Mac asks you two things once:"
let micWords = "Microphone: so your own voice is in the recording."
let soundWords = "Screen & System Audio Recording: so the others in the call are in the recording. "
    + "orch Companion takes only the sound of the call app, never your screen."
let startWords = "Start orch Companion with my Mac"

/// The first-run window, also opened from the menu ("Permissions…").
final class SetupWindow: NSObject {
    var window: NSWindow?
    let micButton = NSButton(title: "Allow microphone", target: nil, action: nil)
    let soundButton = NSButton(title: "Allow call sound", target: nil, action: nil)
    let startBox = NSButton(checkboxWithTitle: startWords, target: nil, action: nil)

    func make() -> NSWindow {
        let w = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 300), styleMask: [.titled, .closable],
                         backing: .buffered, defer: false)
        w.title = "orch Companion"
        w.isReleasedWhenClosed = false
        let title = NSTextField(wrappingLabelWithString: setupTitle)
        title.font = .boldSystemFont(ofSize: 15)
        let intro = NSTextField(wrappingLabelWithString: setupIntro)
        micButton.target = self
        micButton.action = #selector(allowMic)
        soundButton.target = self
        soundButton.action = #selector(allowSound)
        startBox.target = self
        startBox.action = #selector(toggleStart)
        let done = NSButton(title: "Done", target: self, action: #selector(close))
        done.keyEquivalent = "\r"
        func row(_ text: String, _ b: NSButton) -> NSView {
            let l = NSTextField(wrappingLabelWithString: text)
            l.preferredMaxLayoutWidth = 290
            let r = NSStackView(views: [l, b])
            r.alignment = .top
            r.distribution = .fill
            return r
        }
        let stack = NSStackView(views: [title, intro, row(micWords, micButton), row(soundWords, soundButton),
                                        startBox, done])
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 12
        stack.edgeInsets = NSEdgeInsets(top: 18, left: 18, bottom: 18, right: 18)
        for v in [title, intro] { v.preferredMaxLayoutWidth = 420 }
        w.contentView = stack
        refresh()
        return w
    }

    func refresh() {
        let mic = microphoneAllowed()
        micButton.title = mic ? "Allowed" : "Allow microphone"
        micButton.isEnabled = !mic
        let asked = UserDefaults.standard.bool(forKey: "askedCallSound")
        soundButton.title = asked ? "Asked" : "Allow call sound"
        startBox.state = SMAppService.mainApp.status == .enabled ? .on : .off
    }

    func show() {
        if window == nil { window = make() }
        refresh()
        window?.center()
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }

    /// The window as a picture, never shown (for the review card): --render-setup out.png
    func render(to path: String) -> Bool {
        let w = make()
        guard let view = w.contentView else { return false }
        view.appearance = NSAppearance(named: .aqua)
        view.wantsLayer = true
        view.layer?.backgroundColor = NSColor(white: 0.93, alpha: 1).cgColor
        micButton.title = "Allow microphone"
        micButton.isEnabled = true
        soundButton.title = "Allow call sound"
        startBox.state = .on
        view.setFrameSize(NSSize(width: 460, height: max(view.fittingSize.height, 300)))
        view.layoutSubtreeIfNeeded()
        guard let rep = view.bitmapImageRepForCachingDisplay(in: view.bounds) else { return false }
        view.cacheDisplay(in: view.bounds, to: rep)
        guard let png = rep.representation(using: .png, properties: [:]) else { return false }
        return FileManager.default.createFile(atPath: path, contents: png)
    }

    @objc func allowMic() { askMicrophone { [weak self] _ in self?.refresh() } }
    @objc func allowSound() { askCallSound(); refresh() }
    @objc func toggleStart() { setStartWithMac(startBox.state == .on); refresh() }
    @objc func close() { UserDefaults.standard.set(true, forKey: "setupSeen"); window?.close() }
}

// MARK: - start with the Mac

func setStartWithMac(_ on: Bool) {
    do {
        if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
    } catch {
        NSLog("orch Companion: start with the Mac could not be changed: \(error.localizedDescription)")
    }
}

// MARK: - updates

/// "1.2.10" > "1.2.9"; anything not three numbers counts as 0.0.0.
func newer(_ a: String, than b: String) -> Bool {
    func parts(_ s: String) -> [Int] {
        let p = s.split(separator: ".").map { Int($0) ?? -1 }
        return p.count == 3 && !p.contains(where: { $0 < 0 }) ? p : [0, 0, 0]
    }
    return parts(a).lexicographicallyPrecedes(parts(b)) == false && parts(a) != parts(b)
}

/// From the GitHub releases list: the newest "companion-vX.Y.Z" release (not a draft or pre-release) with its zip.
func pickRelease(_ json: Any) -> (version: String, zip: URL)? {
    guard let rows = json as? [[String: Any]] else { return nil }
    var best: (String, URL)?
    for r in rows {
        guard let tag = r["tag_name"] as? String, tag.hasPrefix(releaseTag),
              r["draft"] as? Bool != true, r["prerelease"] as? Bool != true,
              let assets = r["assets"] as? [[String: Any]] else { continue }
        let v = String(tag.dropFirst(releaseTag.count))
        guard newer(v, than: "0.0.0"),
              let a = assets.first(where: { ($0["name"] as? String) == "orch-Companion-\(v).zip" }),
              let u = (a["browser_download_url"] as? String).flatMap(URL.init(string:)),
              u.scheme == "https", u.host == "github.com" else { continue }
        if best == nil || newer(v, than: best!.0) { best = (v, u) }
    }
    return best.map { (version: $0.0, zip: $0.1) }
}

/// The Apple team that signed this running app, or nil for an unsigned (ad-hoc) build.
func myTeam() -> String? {
    var code: SecCode?
    guard SecCodeCopySelf([], &code) == errSecSuccess, let c = code else { return nil }
    var stat: SecStaticCode?
    guard SecCodeCopyStaticCode(c, [], &stat) == errSecSuccess, let s = stat else { return nil }
    var info: CFDictionary?
    guard SecCodeCopySigningInformation(s, SecCSFlags(rawValue: kSecCSSigningInformation), &info) == errSecSuccess,
          let d = info as? [String: Any] else { return nil }
    return d[kSecCodeInfoTeamIdentifier as String] as? String
}

/// True when the app at `url` is a valid, Developer ID signed orch Companion from `team`.
func signedByTeam(_ url: URL, team: String) -> Bool {
    var stat: SecStaticCode?
    guard SecStaticCodeCreateWithPath(url as CFURL, [], &stat) == errSecSuccess, let s = stat else { return false }
    // Developer ID (not a development or App Store certificate), our team, our identifier, notarized.
    let req = "identifier \"io.severin.orch.companion\" and anchor apple generic"
        + " and certificate 1[field.1.2.840.113635.100.6.2.6] exists"
        + " and certificate leaf[field.1.2.840.113635.100.6.1.13] exists"
        + " and certificate leaf[subject.OU] = \"\(team)\" and notarized"
    var r: SecRequirement?
    guard SecRequirementCreateWithString(req as CFString, [], &r) == errSecSuccess else { return false }
    let flags = SecCSFlags(rawValue: kSecCSCheckAllArchitectures | kSecCSStrictValidate | kSecCSCheckNestedCode)
    return SecStaticCodeCheckValidity(s, flags, r) == errSecSuccess
}

/// The version inside a downloaded app (after its signature was checked, so the Info.plist is sealed).
func bundleVersion(_ app: URL) -> String? {
    Bundle(url: app)?.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
}

final class Updater {
    var timer: Timer?
    var status = "Updates: checking"
    var onStatus: ((String) -> Void)?
    var busy: () -> Bool = { false }  // during a call nothing is installed (it would end the recording)

    func start() {
        guard myTeam() != nil else { status = "Updates: only for the signed app"; return }
        check()
        timer = Timer.scheduledTimer(withTimeInterval: updateEvery, repeats: true) { [weak self] _ in self?.check() }
    }

    func say(_ s: String) { DispatchQueue.main.async { self.status = s; self.onStatus?(s) } }

    func check() {
        guard let team = myTeam() else { return }
        if busy() { say("Updates: waiting until the call ends"); return }
        var req = URLRequest(url: releasesURL)
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        req.setValue("orch-companion/\(version)", forHTTPHeaderField: "User-Agent")
        URLSession.shared.dataTask(with: req) { [weak self] data, _, _ in
            guard let self, let data, let json = try? JSONSerialization.jsonObject(with: data),
                  let rel = pickRelease(json) else { self?.say("Updates: could not look"); return }
            guard newer(rel.version, than: version) else { self.say("Up to date (\(version))"); return }
            self.install(rel.zip, version: rel.version, team: team)
        }.resume()
    }

    func install(_ zip: URL, version v: String, team: String) {
        URLSession.shared.downloadTask(with: zip) { [weak self] file, _, _ in
            guard let self, let file else { self?.say("Updates: download failed"); return }
            let dir = FileManager.default.temporaryDirectory.appendingPathComponent("orch-companion-\(UUID())")
            let unzip = Process()
            unzip.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
            unzip.arguments = ["-x", "-k", file.path, dir.path]
            try? unzip.run()
            unzip.waitUntilExit()
            let app = dir.appendingPathComponent("orch Companion.app")
            defer { try? FileManager.default.removeItem(at: dir) }
            guard unzip.terminationStatus == 0, signedByTeam(app, team: team) else {
                self.say("Updates: the download was not signed by us, not installed")
                return
            }
            // never an older or a different version than the release says (no rollback)
            guard let got = bundleVersion(app), got == v, newer(got, than: version) else {
                self.say("Updates: the download is not the newer version, not installed")
                return
            }
            if DispatchQueue.main.sync(execute: { self.busy() }) {
                self.say("Updates: waiting until the call ends")
                return
            }
            do {
                _ = try FileManager.default.replaceItemAt(Bundle.main.bundleURL, withItemAt: app)
            } catch {
                self.say("Updates: could not replace the app")
                return
            }
            self.say("Updated to \(v), starting again")
            DispatchQueue.main.async {
                let again = Process()
                again.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                again.arguments = ["-n", Bundle.main.bundleURL.path]
                try? again.run()
                NSApp.terminate(nil)
            }
        }.resume()
    }
}

func updaterSelftest() -> Int {
    var failed = 0
    for (a, b, want) in [("1.2.10", "1.2.9", true), ("1.2.9", "1.2.10", false), ("1.0.0", "1.0.0", false),
                         ("2.0.0", "1.9.9", true), ("x", "0.0.1", false)] {
        if newer(a, than: b) != want { failed += 1; print("FAIL newer(\(a), \(b))") }
    }
    let rel: [[String: Any]] = [
        ["tag_name": "companion-v0.2.0", "draft": false, "prerelease": false, "assets": [
            ["name": "orch-Companion-0.2.0.zip", "browser_download_url": "https://github.com/x/releases/a.zip"]]],
        ["tag_name": "companion-v0.3.0", "draft": false, "prerelease": true, "assets": [
            ["name": "orch-Companion-0.3.0.zip", "browser_download_url": "https://github.com/x/releases/b.zip"]]],
        ["tag_name": "companion-v0.2.5", "draft": false, "prerelease": false, "assets": [
            ["name": "orch-Companion-0.2.5.zip", "browser_download_url": "http://evil.example/c.zip"]]],
        ["tag_name": "v9.9.9", "assets": []],
    ]
    if pickRelease(rel)?.version != "0.2.0" { failed += 1; print("FAIL pickRelease") }
    print(failed == 0 ? "ok   updates pick the newest signed-for release" : "FAIL updates")
    return failed
}
