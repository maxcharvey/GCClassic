#!/usr/bin/env perl
# Small signed profiles exercise schema, rollback, clipping and restoration.
use strict;
use warnings;
my ($directory)=@ARGV;die "usage: $0 EMPTY_DIRECTORY\n" unless defined $directory && -d $directory;
for my $width(4,8){for my $order('<','>'){
 my $path="$directory/mix_fp${width}_".($order eq '<'?'le':'be').'.bin';
 die "fixture exists\n" if -e $path;
 open my $fh,'>:raw',$path or die "$path: $!";
 my $r=($width==4?'f':'d').$order;my $i='L'.$order;
 my $fp=sub {return unpack($r,pack($r,$_[0]));};
 my ($nx,$nz,$dt)=(3,3,600);my (@q,@ad,@area,@flux,@mask,@threshold,@num,@den,@safe,@bot);
 @ad=(10)x9;@area=(2)x3;@flux=(0)x105;
 @bot=(0)x105;
 my @cc=((0)x3,(.25)x6);my @ze=map {$fp->($_)} ((.2)x6,(0)x3);
 my @term=map {$fp->($_)} ((.8)x3,(.7)x3,(0)x3);
 for my $b(0..34){if($b%5==0||$b%5==2){$bot[$b*3+1]=-2.5;$flux[$b*3+1]=$fp->(-2.5*10/2/$dt);}}
 for my $b(0..34){
  my $initial=$b%5==0?6:($b%5==4?0:$b%5);
  for my $v(0..8){$q[0][$b*9+$v]=$initial;$q[1][$b*9+$v]=$initial;}
  # USA raw negative at longitude1; parent stays positive.
  $q[1][$b*9+3]=-1 if $b%5==1;
  $q[1][$b*9+3]=4 if $b%5==0;
  $threshold[$b]=0;
  for my $x(0..2){
   $mask[$b*3+$x]=($b%5==1 && $x==0)?1:0;
   for my $k(0..2){my $v=$b*9+$k*3+$x;
    $q[2][$v]=($k>=1 && $mask[$b*3+$x])?$q[0][$v]:$q[1][$v];
   }
   # Native three-level forward recurrence and back substitution; nonzero
   # coefficients ensure parser/replay cannot pass by assuming identity.
   my $f0=$fp->($q[2][$b*9+$x]*$term[$x]);
   my $f1=$fp->($fp->($q[2][$b*9+3+$x]+$fp->($cc[3+$x]*$f0))*$term[3+$x]);
   my $inverse=$fp->(1/$fp->(1+$fp->($cc[6+$x]*$fp->(1-$ze[3+$x]))));
   $q[3][$b*9+6+$x]=$fp->($fp->($fp->($q[2][$b*9+6+$x]+$bot[$b*3+$x])+$fp->($cc[6+$x]*$f1))*$inverse);
   $q[3][$b*9+3+$x]=$fp->($f1+$fp->($ze[3+$x]*$q[3][$b*9+6+$x]));
   $q[3][$b*9+$x]=$fp->($f0+$fp->($ze[$x]*$q[3][$b*9+3+$x]));
   for my $k(0..2){my $v=$b*9+$k*3+$x;$q[4][$v]=$q[3][$v]<0?0:$q[3][$v];}
   my ($n,$d)=(0,0);
   for my $k(0..2){$n=$fp->($n+$fp->($q[0][$b*9+$k*3+$x]*$ad[$k*3+$x]));$d=$fp->($d+$fp->($q[4][$b*9+$k*3+$x]*$ad[$k*3+$x]));}
   $n=$fp->($n+$fp->($fp->($flux[$b*3+$x]*$area[$x])*$dt));
   $num[$b*3+$x]=$n;$den[$b*3+$x]=$d;$safe[$b*3+$x]=$d!=0?1:0;
   for my $k(0..2){my $v=$b*9+$k*3+$x;$q[5][$v]=$q[4][$v];$q[5][$v]=$fp->($fp->($q[4][$v]*$n)/$d) if $d!=0;}
  }
 }
 print $fh 'BRCMX001',pack($i.'*',1,3,3,1,1,35,$width,2,2,1,0x01020304,6),pack($r.'*',$dt,@ad,@area,@flux);
 for my $p(0..5){
  print $fh 'BRCMD001',pack($r.'*',@cc,@ze,@term,@bot) if $p==3;
  print $fh pack($i,$p+1),pack($r.'*',@{$q[$p]});
 }
 print $fh pack($r.'*',@threshold),pack($i.'*',@mask),pack($r.'*',@num,@den),pack($i.'*',@safe);
 close $fh or die "$path: $!";print "$path\n";
}}
