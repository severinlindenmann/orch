import Foundation
import Observation
import SwiftUI

// Logic behind the artifact viewer and the comment pins (views: ArtifactViewer.swift, ArtifactSurfaces.swift, CommentPins.swift).

/// Something the viewer can open: a published page or app, a picture or a file from the relay, an uploaded blob.
struct ArtifactItem: Identifiable, Equatable, Sendable {
    /// What the viewer does with it.
    enum Kind: Equatable, Sendable { case html, pdf, image, file, link }

    var id: String
    var title: String
    /// Stable per artifact across revisions (`a_...`) and this revision; feedback needs both (older workspaces send none).
    var artifactId: String?
    var rev: String?
    var kind: Kind
    var url: URL?
    var blobId: String?
    var name: String?
    var mime: String?
    /// The topic that feedback is sent to. Feedback needs a topic (never General).
    var conversation: ConversationID?

    /// Looks good / Comment need the artifact id and revision and a topic to send them to.
    var canGiveFeedback: Bool {
        guard artifactId != nil, rev != nil, kind != .link else { return false }
        if case .topic = conversation { return true } else { return false }
    }

    /// A ticket attachment (html, image, file, link, pr, commit).
    init(_ a: TicketSnapshot.Attachment, in conversation: ConversationID? = nil) {
        id = a.id; title = a.label ?? a.name ?? "Preview"; artifactId = a.artifactId; rev = a.rev
        url = a.url.flatMap(URL.init(string:)); blobId = a.blobId; name = a.name; self.conversation = conversation
        mime = a.name.map(MediaPrep.mime(forFileName:))
        switch a.kind {
        case "html": kind = .html
        case "image": kind = .image
        case "file": kind = Self.isPDF(name: a.name, mime: nil) ? .pdf : .file
        default: kind = .link
        }
    }

    /// An image or file in a message (a photo sent from the phone, a proof file of an update).
    init(_ a: MessageAttachment, in conversation: ConversationID? = nil) {
        id = a.blobId; title = a.name; blobId = a.blobId; name = a.name; mime = a.mime; self.conversation = conversation
        kind = a.kind == .image ? .image : (Self.isPDF(name: a.name, mime: a.mime) ? .pdf : .file)
    }

    init(id: String, title: String, kind: Kind, url: URL? = nil, blobId: String? = nil, name: String? = nil, mime: String? = nil,
         artifactId: String? = nil, rev: String? = nil, conversation: ConversationID? = nil) {
        self.id = id; self.title = title; self.kind = kind; self.url = url; self.blobId = blobId; self.name = name; self.mime = mime
        self.artifactId = artifactId; self.rev = rev; self.conversation = conversation
    }

    static func isPDF(name: String?, mime: String?) -> Bool {
        mime == "application/pdf" || (name?.lowercased().hasSuffix(".pdf") ?? false)
    }

    /// "Web page preview · v2".
    var subtitle: String {
        let k: String
        switch kind { case .html: k = "Web page preview"; case .pdf: k = "PDF"; case .image: k = "Picture"; case .file: k = "File"; case .link: k = "Link" }
        guard let rev else { return k }
        return "\(k) · \(rev.count > 8 ? String(rev.prefix(7)) : rev)"
    }
}

// MARK: Pins

/// One comment on the artifact. `anchor` is what goes to the workspace; `place` is only for drawing the pin again on this phone.
struct PinDraftItem: Identifiable, Equatable, Sendable {
    /// Where the pin is drawn, as fractions of the document (html: width and page height), the page (pdf) or the picture (image).
    struct Place: Equatable, Sendable { var x: Double; var y: Double; var page: Int? = nil }
    var n: Int
    var anchor: Anchor
    var place: Place
    var text: String = ""
    var voiceFile: URL? = nil
    var transcript: String? = nil
    var id: Int { n }
    /// A pin needs a written or spoken comment.
    var isComplete: Bool { !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || voiceFile != nil }
}

/// The open comment session of one viewer: pins in order (numbered from 1), the pin being edited, and the message they become.
@MainActor @Observable
final class PinStore {
    private(set) var pins: [PinDraftItem] = []
    /// The pin in the editor: a new one (not in `pins` yet) or an existing one.
    var editing: PinDraftItem?
    var isEditingNew = false

    var count: Int { pins.count }

    /// A tap at `anchor`/`place` opens the editor for a new pin.
    func beginPin(anchor: Anchor, place: PinDraftItem.Place) {
        editing = PinDraftItem(n: (pins.map(\.n).max() ?? 0) + 1, anchor: anchor, place: place); isEditingNew = true
    }
    func edit(_ n: Int) { if let p = pins.first(where: { $0.n == n }) { editing = p; isEditingNew = false } }
    func cancelEdit() { editing = nil; isEditingNew = false }
    /// Saves the editor's pin; refuses an empty one (returns false).
    @discardableResult
    func saveEdit() -> Bool {
        guard var p = editing, p.isComplete else { return false }
        p.text = p.text.trimmingCharacters(in: .whitespacesAndNewlines)
        if let i = pins.firstIndex(where: { $0.n == p.n }) { pins[i] = p } else { pins.append(p) }
        editing = nil; isEditingNew = false
        return true
    }
    func remove(_ n: Int) { pins.removeAll { $0.n == n }; renumber(); editing = nil; isEditingNew = false }
    func reset() { pins = []; editing = nil; isEditingNew = false }

    /// Keeps the numbers 1...count after a delete, in order.
    private func renumber() { for i in pins.indices { pins[i].n = i + 1 } }

    /// "Send comments (3)": changes with every pin; nil when there is none (use `approveDraft` for Looks good).
    func changesDraft(for item: ArtifactItem) -> DraftFeedback? {
        guard let id = item.artifactId, let rev = item.rev, !pins.isEmpty else { return nil }
        return DraftFeedback(artifactId: id, artifactRev: rev, verdict: .changes,
                             pins: pins.map { DraftPin(n: $0.n, anchor: $0.anchor, text: $0.text.isEmpty ? nil : $0.text, voiceFile: $0.voiceFile, transcript: $0.transcript) })
    }
    /// "Looks good": approve, no pins.
    static func approveDraft(for item: ArtifactItem) -> DraftFeedback? {
        guard let id = item.artifactId, let rev = item.rev else { return nil }
        return DraftFeedback(artifactId: id, artifactRev: rev, verdict: .approve, pins: [])
    }
}

// MARK: Anchors (contracts/relay-api.md "feedback")

enum AnchorMaker {
    /// Fractions of 0...1, clamped, from the top-left.
    static func fraction(_ v: Double) -> Double { min(1, max(0, v)) }

    static func pdf(page: Int, x: Double, y: Double) -> Anchor { Anchor(type: .pdf, page: page, x: fraction(x), y: fraction(y)) }
    static func image(x: Double, y: Double) -> Anchor { Anchor(type: .image, x: fraction(x), y: fraction(y)) }
    /// A selector and/or a quote, the scroll offset in px and the viewport width.
    static func html(selector: String?, quote: String?, offset: Int, viewportW: Int) -> Anchor? {
        let s = selector.flatMap { $0.isEmpty ? nil : String($0.prefix(500)) }
        let q = quote.map { String($0.trimmingCharacters(in: .whitespacesAndNewlines).prefix(160)) }.flatMap { $0.isEmpty ? nil : $0 }
        guard s != nil || q != nil else { return nil }
        return Anchor(type: .html, selector: s, quote: q, offset: max(0, offset), viewportW: max(0, viewportW))
    }

    /// What the injected script posts when a tap lands on the page: {selector, quote, offset, viewportW, fx, fy}.
    static func html(fromScript body: Any) -> (anchor: Anchor, place: PinDraftItem.Place)? {
        guard let d = body as? [String: Any], d["kind"] as? String == "place",
              let a = html(selector: d["selector"] as? String, quote: d["quote"] as? String,
                           offset: (d["offset"] as? NSNumber)?.intValue ?? 0, viewportW: (d["viewportW"] as? NSNumber)?.intValue ?? 0),
              let fx = (d["fx"] as? NSNumber)?.doubleValue, let fy = (d["fy"] as? NSNumber)?.doubleValue else { return nil }
        return (a, .init(x: fraction(fx), y: fraction(fy)))
    }
}

/// The user script injected into every html artifact. In comment mode a tap (finger moved < 8 px, page not scrolled) posts the
/// anchor to the `orchPin` handler; a drag scrolls as usual. Pins are drawn inside the page (they scroll with it).
enum AnchorScript {
    static let handler = "orchPin"
    static let source = #"""
    (function () {
      if (window.__orch) return;
      var mode = false, down = null, pins = [];
      var layer = document.createElement('div');
      layer.style.cssText = 'position:absolute;left:0;top:0;width:0;height:0;z-index:2147483647;';
      function post(m) { window.webkit.messageHandlers.orchPin.postMessage(m); }
      function ready(f) { if (document.body) f(); else document.addEventListener('DOMContentLoaded', f); }
      function esc(s) { return (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&'); }
      function selectorOf(el) {
        var parts = [];
        while (el && el.nodeType === 1 && el !== document.documentElement && parts.length < 8) {
          if (el.id) { parts.unshift('#' + esc(el.id)); break; }
          var tag = el.tagName.toLowerCase(), i = 1, s = el;
          while ((s = s.previousElementSibling)) if (s.tagName === el.tagName) i++;
          parts.unshift(tag + ':nth-of-type(' + i + ')');
          el = el.parentElement;
        }
        return parts.join(' > ');
      }
      function quoteOf(el) {
        var t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
        return t.slice(0, 160);
      }
      function docW() { return Math.max(document.documentElement.scrollWidth, 1); }
      function docH() { return Math.max(document.documentElement.scrollHeight, 1); }
      function draw() {
        layer.innerHTML = '';
        pins.forEach(function (p) {
          var b = document.createElement('button');
          b.textContent = String(p.n);
          b.setAttribute('data-orch-pin', String(p.n));
          b.setAttribute('aria-label', 'Edit comment ' + p.n);
          b.style.cssText = 'position:absolute;width:30px;height:30px;margin:-15px 0 0 -15px;border-radius:50%;border:2px solid #06231c;background:#2fc6a3;color:#06231c;font:700 14px -apple-system,sans-serif;padding:0;left:' + (p.x * docW()) + 'px;top:' + (p.y * docH()) + 'px;';
          b.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); post({ kind: 'edit', n: p.n }); }, true);
          layer.appendChild(b);
        });
      }
      document.addEventListener('pointerdown', function (e) {
        if (!mode || e.target.closest('[data-orch-pin]')) return;
        down = { x: e.clientX, y: e.clientY, sy: window.scrollY, sx: window.scrollX };
      }, true);
      document.addEventListener('pointercancel', function () { down = null; }, true);
      document.addEventListener('pointerup', function (e) {
        if (!mode || !down) return;
        var d = down; down = null;
        if (Math.hypot(e.clientX - d.x, e.clientY - d.y) > 8 || Math.abs(window.scrollY - d.sy) > 3 || Math.abs(window.scrollX - d.sx) > 3) return;
        var el = document.elementFromPoint(e.clientX, e.clientY) || document.body;
        post({ kind: 'place', selector: selectorOf(el), quote: quoteOf(el), offset: Math.round(window.scrollY), viewportW: Math.round(window.innerWidth),
               fx: (e.clientX + window.scrollX) / docW(), fy: (e.clientY + window.scrollY) / docH() });
      }, true);
      document.addEventListener('click', function (e) { if (mode && !e.target.closest('[data-orch-pin]')) { e.preventDefault(); e.stopPropagation(); } }, true);
      window.__orch = {
        setMode: function (on) { mode = !!on; },
        setPins: function (list) { pins = list || []; ready(function () { if (!layer.parentNode) document.body.appendChild(layer); draw(); }); },
        scrollTo: function (y) { window.scrollTo(0, y); }
      };
    })();
    """#

    static func setMode(_ on: Bool) -> String { "window.__orch && window.__orch.setMode(\(on));" }
    static func setPins(_ pins: [PinDraftItem]) -> String {
        let items = pins.map { "{n:\($0.n),x:\($0.place.x),y:\($0.place.y)}" }.joined(separator: ",")
        return "window.__orch && window.__orch.setPins([\(items)]);"
    }
}

/// Everything a viewer may not load: no web address at all (a published page works from the decrypted bytes only).
enum NetworkBlock {
    static let identifier = "orch-no-network"
    static let rules = #"""
    [{"trigger":{"url-filter":"^(https?|wss?|ftp)://.*"},"action":{"type":"block"}}]
    """#
    /// The custom scheme the viewer serves decrypted pages from.
    static let scheme = "orch-page"
}

/// Where the viewer gets its bytes. The default goes to the network; a test or demo host puts its own in the environment.
struct ArtifactLoader: Sendable {
    var publish: @Sendable (PublishLink) async throws -> PublishContent = { try await PublishFetcher().load($0) }
    /// A blob by id; nil = use the paired relay (`AppModel.blob`).
    var blob: (@Sendable (String) async -> Data?)? = nil
    static let live = ArtifactLoader()
}
extension EnvironmentValues {
    @Entry var artifactLoader = ArtifactLoader.live
}
