#!/usr/bin/env perl
# Opt-in BrC diagnostics for a generated v14.8 HISTORY.rc; no physics edits.
use strict;
use warnings;
use Getopt::Long qw(GetOptions);
my ($file, $short, $monthly) = ('', 0, 0);
GetOptions('history=s' => \$file, 'short-test-hourly' => \$short, 'monthly' => \$monthly)
    or die "Usage: $0 --history HISTORY.rc [--short-test-hourly]\n";
$file && !@ARGV or die "Usage: $0 --history HISTORY.rc [--short-test-hourly]\n";
open my $in, '<', $file or die "$file: $!\n";
local $/; my $text = <$in>; close $in;
my @aerosol = qw(PBRCPOA NPBRCPOA DBRCPOA BRCSOA WTC FSOAS);
my @family = (@aerosol, 'FSOAP');
my %fields = (
 BrCDryDep => [map { my $p = $_; map { "${p}_$_" } @aerosol } qw(DryDep DryDepVel)],
 BrCWetLoss => [map { my $p = $_; map { "${p}_$_" } @aerosol } qw(WetLossConv WetLossConvFrac WetLossLS)],
 BrCProcessBudget => [
  (map { my $p = $_; map { "Budget${p}Full_$_" } @family } qw(EmisDryDep Chemistry Transport Mixing Convection)),
  (map { "BudgetWetDepFull_$_" } @aerosol)
 ],
);
# Never replace unrelated collections or manually authored blocks with these names.
$text =~ s/\n# BEGIN managed BrC deposition\n.*?# END managed BrC deposition\n//s;
for my $name (keys %fields) {
    $text !~ /^\s*\Q$name\E\./m or die "Unmanaged $name block exists; refusing overwrite\n";
}
$text =~ s{(^COLLECTIONS:.*?^::)}{
 my $decl = $1;
 $decl =~ s/^\s*'(?:BrCDryDep|BrCWetLoss|BrCProcessBudget)',?\s*\n//mg;
 $decl =~ s/^::/             'BrCDryDep',\n             'BrCWetLoss',\n             'BrCProcessBudget',\n::/m;
 $decl;
}mse or die "Missing COLLECTIONS declaration\n";
die "Cannot combine --monthly and --short-test-hourly\n" if $short && $monthly;
my $cadence = $monthly ? '00000100 000000' : $short ? '00000000 010000' : '00000001 000000';
# A blank line after an inactive block can make Classic's HISTORY reader
# skip the next block. Keep the appended boundary free of blank lines.
$text =~ s/\s*\z/\n/;
$text .= "# BEGIN managed BrC deposition\n";
$text .= "# Dry flux: molec cm-2 s-1; velocity: cm s-1; wet loss/budgets: kg s-1.\n";
$text .= "# FSOAP has no deposition flags. EmisDryDep is a combined operator budget.\n";
for my $name (qw(BrCDryDep BrCWetLoss BrCProcessBudget)) {
 $text .= "  $name.template: '%y4%m2%d2_%h2%n2z.nc4',\n";
 $text .= "  $name.frequency: $cadence\n  $name.duration: $cadence\n";
 $text .= "  $name.mode: 'time-averaged'\n";
 my @f = @{$fields{$name}};
 $text .= "  $name.fields: '" . shift(@f) . "',\n";
 $text .= join('', map { "                    '$_',\n" } @f);
 $text .= "::\n";
}
$text .= "# END managed BrC deposition\n";
# Replace only after all validation; preserve permissions and retain a backup.
my $tmp = "$file.brc.tmp";
!-e $tmp or die "Temporary file already exists: $tmp\n";
open my $out, '>', $tmp or die "$tmp: $!\n";
print {$out} $text or die "Write failed: $!\n";
close $out or die "Close failed: $!\n";
chmod((stat($file))[2] & 07777, $tmp) or die "chmod: $!\n";
if (!-e "$file.before_brc") {
 require File::Copy; File::Copy::copy($file, "$file.before_brc") or die "Backup failed: $!\n";
}
rename $tmp, $file or die "Rename failed: $!\n";
print "Enabled BrCDryDep (12), BrCWetLoss (18), BrCProcessBudget (41); cadence $cadence\n";
