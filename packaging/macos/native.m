// Native presentation/bootstrap only. Workloads belong to the existing supervisor.
#import <Cocoa/Cocoa.h>
#import <sys/stat.h>
#import <unistd.h>
#import <stdio.h>
#import <string.h>
#import <dispatch/dispatch.h>

static NSString *field(NSDictionary *value, NSString *key, NSString *fallback) {
    id item = value[key];
    return [item isKindOfClass:NSString.class] ? item : fallback;
}

static void answer(NSString *action) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"action": action} options:0 error:NULL];
    [[NSFileHandle standardOutput] writeData:data];
    [[NSFileHandle standardOutput] writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]];
}

static NSImage *stationIcon(void) {
    NSImage *image = [[NSImage alloc] initWithSize:NSMakeSize(64, 64)];
    [image lockFocus];
    [[NSColor colorWithSRGBRed:0.10 green:0.11 blue:0.16 alpha:1] setFill];
    [[NSBezierPath bezierPathWithRoundedRect:NSMakeRect(0, 0, 64, 64) xRadius:15 yRadius:15] fill];
    NSBezierPath *spark = [NSBezierPath bezierPath];
    [spark moveToPoint:NSMakePoint(32, 54)];
    [spark lineToPoint:NSMakePoint(38, 38)];
    [spark lineToPoint:NSMakePoint(54, 32)];
    [spark lineToPoint:NSMakePoint(38, 26)];
    [spark lineToPoint:NSMakePoint(32, 10)];
    [spark lineToPoint:NSMakePoint(26, 26)];
    [spark lineToPoint:NSMakePoint(10, 32)];
    [spark lineToPoint:NSMakePoint(26, 38)];
    [spark closePath];
    NSGradient *gradient = [[NSGradient alloc] initWithStartingColor:
        [NSColor colorWithSRGBRed:0.66 green:0.51 blue:1 alpha:1]
        endingColor:[NSColor colorWithSRGBRed:0.30 green:0.85 blue:0.86 alpha:1]];
    [gradient drawInBezierPath:spark angle:-45];
    [image unlockFocus];
    return image;
}

static void prepareUI(NSApplicationActivationPolicy policy) {
    [NSApplication sharedApplication];
    [NSApp setActivationPolicy:policy];
    NSApp.appearance = [NSAppearance appearanceNamed:NSAppearanceNameDarkAqua];
    NSApp.applicationIconImage = stationIcon();
    [NSApp activateIgnoringOtherApps:YES];
}

static int showDialog(BOOL running) {
    NSData *input = [[NSFileHandle standardInput] readDataOfLength:16385];
    if (input.length > 16384) return 2;
    id request = [NSJSONSerialization JSONObjectWithData:input options:0 error:NULL];
    if (![request isKindOfClass:NSDictionary.class]) return 2;
    prepareUI(NSApplicationActivationPolicyAccessory);
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"AI Station";
    alert.informativeText = field(request, @"text", @"");
    alert.icon = stationIcon();
    alert.alertStyle = [field(request, @"kind", @"") isEqual:@"error"] ? NSAlertStyleWarning : NSAlertStyleInformational;
    if (running) {
        [alert addButtonWithTitle:@"Open AI Station"];
        [alert addButtonWithTitle:@"Run in background"];
        [alert addButtonWithTitle:@"Stop AI Station"];
        alert.buttons[1].keyEquivalent = @"\033";
    } else {
        [alert addButtonWithTitle:field(request, @"ok", @"Continue")];
        if (request[@"cancel"]) [alert addButtonWithTitle:field(request, @"cancel", @"Cancel")];
    }
    NSModalResponse result = [alert runModal];
    if (running) {
        answer(result == NSAlertFirstButtonReturn ? @"open" : result == NSAlertThirdButtonReturn ? @"stop" : @"background");
        return 0;
    }
    answer(result == NSAlertFirstButtonReturn ? @"ok" : @"cancel");
    return result == NSAlertFirstButtonReturn ? 0 : 1;
}

@interface ProgressDelegate : NSObject <NSWindowDelegate>
@end
@implementation ProgressDelegate
- (void)windowWillClose:(NSNotification *)notification { [NSApp terminate:nil]; }
@end
static ProgressDelegate *progressDelegate;

static int progressWindow(BOOL smoke) {
    prepareUI(NSApplicationActivationPolicyAccessory);
    NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 480, 176)
        styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        backing:NSBackingStoreBuffered defer:NO];
    window.title = @"AI Station";
    window.releasedWhenClosed = NO;
    progressDelegate = [ProgressDelegate new];
    window.delegate = progressDelegate;
    NSTextField *heading = [NSTextField labelWithString:@"Your local workstation is starting"];
    heading.font = [NSFont systemFontOfSize:17 weight:NSFontWeightSemibold];
    heading.frame = NSMakeRect(28, 112, 424, 28);
    NSTextField *stage = [NSTextField wrappingLabelWithString:@"Preparing AI Station…"];
    stage.font = [NSFont systemFontOfSize:13];
    stage.textColor = NSColor.secondaryLabelColor;
    stage.frame = NSMakeRect(28, 61, 424, 44);
    NSProgressIndicator *indicator = [[NSProgressIndicator alloc] initWithFrame:NSMakeRect(28, 31, 424, 16)];
    indicator.style = NSProgressIndicatorStyleBar;
    indicator.indeterminate = YES;
    [indicator startAnimation:nil];
    [window.contentView addSubview:heading];
    [window.contentView addSubview:stage];
    [window.contentView addSubview:indicator];
    NSTextField *hint = [NSTextField labelWithString:@"Setup continues if you close this window."];
    hint.font = [NSFont systemFontOfSize:11];
    hint.textColor = NSColor.tertiaryLabelColor;
    hint.frame = NSMakeRect(28, 6, 424, 18);
    [window.contentView addSubview:hint];
    [window center];
    [window makeKeyAndOrderFront:nil];
    if (smoke) {
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC), dispatch_get_main_queue(), ^{
            answer(@"native-ui-smoke-passed");
            [NSApp terminate:nil];
        });
    } else {
        dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            char buffer[16385];
            while (fgets(buffer, sizeof(buffer), stdin)) {
                @autoreleasepool {
                    size_t length = strlen(buffer);
                    if (!length || buffer[length - 1] != '\n') break;
                    NSData *data = [NSData dataWithBytes:buffer length:length];
                    id value = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL];
                    if (![value isKindOfClass:NSDictionary.class]) break;
                    NSString *text = field(value, @"stage", @"");
                    if (text.length > 4096) break;
                    dispatch_async(dispatch_get_main_queue(), ^{ stage.stringValue = text; });
                }
            }
            dispatch_async(dispatch_get_main_queue(), ^{ [NSApp terminate:nil]; });
        });
    }
    [NSApp run];
    return 0;
}

@interface StationDelegate : NSObject <NSApplicationDelegate>
@property(strong) NSTask *launcher;
@property(strong) NSURL *resources;
@property(assign) BOOL stopping;
@property(strong) NSMutableArray<NSTask *> *reopenTasks;
@end

@implementation StationDelegate
- (NSURL *)retainedResources {
    NSData *data = [NSData dataWithContentsOfURL:[self.resources URLByAppendingPathComponent:@"desktop-manifest.json"]];
    id raw = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
    NSDictionary *manifest = [raw isKindOfClass:NSDictionary.class] ? raw : @{};
    NSString *identity = field(manifest, @"bundle_id", @"");
    NSCharacterSet *invalid = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet];
    if (identity.length != 64 || [identity rangeOfCharacterFromSet:invalid].location != NSNotFound) return self.resources;
    NSString *home = NSProcessInfo.processInfo.environment[@"HOME"] ?: NSHomeDirectory();
    NSString *path = [[home stringByAppendingPathComponent:@"Library/Application Support/AI Station/releases"] stringByAppendingPathComponent:identity];
    struct stat info;
    if (lstat(path.fileSystemRepresentation, &info) || !S_ISDIR(info.st_mode) || info.st_uid != getuid() || (info.st_mode & 0022)) return self.resources;
    return [NSURL fileURLWithPath:path isDirectory:YES];
}
- (NSTask *)taskAt:(NSURL *)root arguments:(NSArray<NSString *> *)arguments {
    NSTask *task = [NSTask new];
    task.executableURL = [root URLByAppendingPathComponent:@"python/bin/python3.12"];
    task.arguments = [@[@"-IB", [root URLByAppendingPathComponent:@"scripts/desktop.py"].path] arrayByAddingObjectsFromArray:arguments];
    task.currentDirectoryURL = root;
    return task;
}
- (void)openStation:(id)sender {
    if (self.stopping) return;
    NSTask *task = [self taskAt:[self retainedResources] arguments:@[]];
    __weak StationDelegate *weakSelf = self;
    task.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf.reopenTasks removeObject:finished]; });
    };
    NSError *error = nil;
    if ([task launchAndReturnError:&error]) [self.reopenTasks addObject:task];
}
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    self.resources = NSBundle.mainBundle.resourceURL;
    self.reopenTasks = [NSMutableArray new];
    self.launcher = [self taskAt:self.resources arguments:@[@"--background"]];
    __weak StationDelegate *weakSelf = self;
    self.launcher.terminationHandler = ^(NSTask *finished) {
        dispatch_async(dispatch_get_main_queue(), ^{
            StationDelegate *strongSelf = weakSelf;
            if (strongSelf.stopping) [NSApp replyToApplicationShouldTerminate:YES];
            else {
                if (finished.terminationStatus != 0) {
                    NSAlert *alert = [NSAlert new];
                    alert.messageText = @"AI Station could not start";
                    alert.informativeText = @"Check the application package and Docker Desktop, then open AI Station again.";
                    alert.icon = stationIcon();
                    [alert runModal];
                }
                [NSApp terminate:nil];
            }
        });
    };
    NSError *error = nil;
    if (![self.launcher launchAndReturnError:&error]) {
        NSAlert *alert = [NSAlert new];
        alert.messageText = @"AI Station could not open";
        alert.informativeText = @"The application package is incomplete. Reinstall the application while keeping its saved data.";
        [alert runModal];
        [NSApp terminate:nil];
    }
}
- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)visible {
    [self openStation:nil];
    return YES;
}
- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender {
    if (!self.launcher.running) return NSTerminateNow;
    self.stopping = YES;
    [self.launcher terminate]; // Only this NSTask child; the Python supervisor owns shutdown.
    return NSTerminateLater;
}
@end
static StationDelegate *stationDelegate;

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        NSString *mode = argc > 1 ? [NSString stringWithUTF8String:argv[1]] : @"";
        if ([mode isEqual:@"--native-dialog"]) return showDialog(NO);
        if ([mode isEqual:@"--native-running"]) return showDialog(YES);
        if ([mode isEqual:@"--native-progress"]) return progressWindow(NO);
        if ([mode isEqual:@"--native-ui-smoke"]) return progressWindow(YES);
        NSSet *allowed = [NSSet setWithArray:@[@"--console", @"--background", @"--status", @"--stop", @"--package-check"]];
        NSMutableArray *arguments = [NSMutableArray new];
        for (int i = 1; i < argc; i++) {
            NSString *value = [NSString stringWithUTF8String:argv[i]];
            if (![allowed containsObject:value]) return 2;
            [arguments addObject:value];
        }
        if (arguments.count) {
            StationDelegate *entry = [StationDelegate new];
            NSTask *task = [entry taskAt:NSBundle.mainBundle.resourceURL arguments:arguments];
            if (![task launchAndReturnError:NULL]) return 1;
            [task waitUntilExit];
            return task.terminationStatus;
        }
        prepareUI(NSApplicationActivationPolicyRegular);
        stationDelegate = [StationDelegate new];
        NSMenu *menu = [NSMenu new];
        NSMenuItem *item = [NSMenuItem new];
        [menu addItem:item];
        NSMenu *application = [[NSMenu alloc] initWithTitle:@"AI Station"];
        NSMenuItem *open = [[NSMenuItem alloc] initWithTitle:@"Open AI Station" action:@selector(openStation:) keyEquivalent:@"o"];
        open.target = stationDelegate;
        [application addItem:open];
        [application addItem:NSMenuItem.separatorItem];
        [application addItemWithTitle:@"Quit AI Station" action:@selector(terminate:) keyEquivalent:@"q"];
        item.submenu = application;
        NSApp.mainMenu = menu;
        NSApp.delegate = stationDelegate;
        [NSApp run];
        return 0;
    }
}
